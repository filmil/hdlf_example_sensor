// SPDX-License-Identifier: Apache-2.0

// Package dfuutil holds what dfu-util, the flash tool of //fw:flash, is
// built from (issue #14, step 5): the container image, the package
// snapshot, libusb's and dfu-util's sources, each pinned, and the podman
// command that runs build.sh (embedded) to build it.
package dfuutil

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Image is Ubuntu 26.04, pinned by digest: the image the org's other
// operator-run builds use (bazel_rules_kicad's tools/kicad_prebuilt, whose
// pattern this tool follows).
const Image = "docker.io/library/ubuntu:26.04@sha256:5e275723f82c67e387ba9e3c24baa0abdcb268917f276a0561c97bef9450d0b4"

// AptSnapshot is the time of snapshot.ubuntu.com every package comes from,
// so each package's version is fixed.
const AptSnapshot = "20261117T000000Z"

// Input is one downloaded file, pinned by sha256.
type Input struct {
	URL    string
	SHA256 string
}

// LibUSB is libusb 1.0.30's release tarball; GitHub's release lists its
// sha256.
var LibUSB = Input{
	URL:    "https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2",
	SHA256: "fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf",
}

// DfuUtil is dfu-util 0.11's release tarball; it matches the MD5 the
// project publishes beside it (31c983543a1fe8f03260ca4d56ad4f43).
var DfuUtil = Input{
	URL:    "https://dfu-util.sourceforge.net/releases/dfu-util-0.11.tar.gz",
	SHA256: "b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e",
}

// BinarySHA256 is the static dfu-util's sha256: what MODULE.bazel pins and
// tools/mirror/manifest.json mirrors. The tool fails on any other.
const BinarySHA256 = "95fdbb4cdaefe1762bd88f5b97ff5da1b8cf997a9bcf65c4cdf15658dd917106"

// LicensesSHA256 is dfu-util-licenses.tar's sha256, as the manifest pins it.
const LicensesSHA256 = "02feea0341615fcb1a5415153c6d300a4e4bec6b7a3e96abe1a5707c3e6368b8"

// Outputs are the files build.sh leaves in --out: the binary, the two
// sources under their upstream names, the licences and SHA256SUMS.
func Outputs() []string {
	return []string{"dfu-util", filepath.Base(LibUSB.URL), filepath.Base(DfuUtil.URL), "dfu-util-licenses.tar", "SHA256SUMS"}
}

//go:embed build.sh
var BuildScript string

// CABundles are where Linux distributions keep the CA bundle, in the order
// tried. apt in the container checks snapshot.ubuntu.com against it; it
// verifies the connection only, and reaches no output.
var CABundles = []string{
	"/etc/ssl/certs/ca-certificates.crt", // Debian, Ubuntu, Arch
	"/etc/pki/tls/certs/ca-bundle.crt",   // Fedora, RHEL
	"/etc/ssl/ca-bundle.pem",             // openSUSE
}

// CopyCABundle copies the first of CABundles that exists into dir, and
// returns the copy's path. The container mounts the copy, never the host's
// file: podman's :Z relabels what it mounts.
func CopyCABundle(dir string) (string, error) {
	src, err := FindCABundle()
	if err != nil {
		return "", err
	}
	b, err := os.ReadFile(src)
	if err != nil {
		return "", err
	}
	dst := filepath.Join(dir, "ca.crt")
	return dst, os.WriteFile(dst, b, 0o444)
}

// FindCABundle returns the first of CABundles that exists.
func FindCABundle() (string, error) {
	for _, p := range CABundles {
		if fi, err := os.Stat(p); err == nil && fi.Mode().IsRegular() {
			return p, nil
		}
	}
	return "", fmt.Errorf("no CA bundle at any of %v", CABundles)
}

// Command returns the podman command line that builds dfu-util in out (an
// absolute directory with no ":") with jobs parallel compile jobs. The only
// host files the container sees are out and ca, read-only: the tool's own
// copy of the CA bundle (CopyCABundle).
func Command(out, ca string, jobs int) []string {
	args := []string{"podman", "run", "--rm", "-i",
		"--platform=linux/amd64",
		fmt.Sprintf("--cpus=%d", jobs),
		"-v", out + ":/out:Z",
		"-v", ca + ":/host-ca.crt:ro,Z",
	}
	env := []string{
		"APT_SNAPSHOT=" + AptSnapshot,
		"LIBUSB_URL=" + LibUSB.URL,
		"LIBUSB_SHA256=" + LibUSB.SHA256,
		"DFU_UTIL_URL=" + DfuUtil.URL,
		"DFU_UTIL_SHA256=" + DfuUtil.SHA256,
		fmt.Sprintf("JOBS=%d", jobs),
	}
	sort.Strings(env)
	for _, e := range env {
		args = append(args, "-e", e)
	}
	// The script comes on standard input: bash -s reads it from there.
	return append(args, Image, "bash", "-s")
}

// ResolveOut makes --out absolute: a relative one is taken from wd, the
// directory bazel run was started in. podman's -v splits on ":", so a path
// with one is refused.
func ResolveOut(out, wd string) (string, error) {
	if out == "" {
		return "", fmt.Errorf("--out is required")
	}
	abs := out
	if !filepath.IsAbs(abs) {
		if !filepath.IsAbs(wd) {
			return "", fmt.Errorf("--out %q is relative, and the working directory %q is not absolute; give an absolute --out", out, wd)
		}
		abs = filepath.Join(wd, abs)
	}
	abs = filepath.Clean(abs)
	if strings.Contains(abs, ":") {
		return "", fmt.Errorf("--out %q has a \":\", which podman's -v cannot take", abs)
	}
	return abs, nil
}

// CheckOut fails unless dir is missing or empty: an old binary left there
// would pass for a new one.
func CheckOut(dir string) error {
	entries, err := os.ReadDir(dir)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return nil
	case err != nil:
		return fmt.Errorf("--out: %w", err)
	case len(entries) > 0:
		return fmt.Errorf("--out %s is not empty", dir)
	}
	return nil
}

// VerifyFile fails unless the file at p has the sha256 want.
func VerifyFile(p, want string) error {
	f, err := os.Open(p)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return err
	}
	if got := hex.EncodeToString(h.Sum(nil)); got != want {
		return fmt.Errorf("%s has sha256 %s; want %s", p, got, want)
	}
	return nil
}

// SHA256SUMS is what build.sh writes to SHA256SUMS when every output has
// its pinned sha256.
func SHA256SUMS() string {
	return BinarySHA256 + "  dfu-util\n" +
		LibUSB.SHA256 + "  " + filepath.Base(LibUSB.URL) + "\n" +
		DfuUtil.SHA256 + "  " + filepath.Base(DfuUtil.URL) + "\n" +
		LicensesSHA256 + "  dfu-util-licenses.tar\n"
}

// VerifyOutput checks what the build left in dir against the pins: the
// binary, the licences, both sources, and SHA256SUMS, line by line. On any
// mismatch it empties dir (CleanOut) and returns every error.
func VerifyOutput(dir string) error {
	pins := map[string]string{
		"dfu-util":                 BinarySHA256,
		"dfu-util-licenses.tar":    LicensesSHA256,
		filepath.Base(LibUSB.URL):  LibUSB.SHA256,
		filepath.Base(DfuUtil.URL): DfuUtil.SHA256,
	}
	var errs []error
	for _, name := range Outputs() {
		if want, pinned := pins[name]; pinned {
			if err := VerifyFile(filepath.Join(dir, name), want); err != nil {
				errs = append(errs, err)
			}
		}
	}
	sums, err := os.ReadFile(filepath.Join(dir, "SHA256SUMS"))
	switch {
	case err != nil:
		errs = append(errs, err)
	case string(sums) != SHA256SUMS():
		errs = append(errs, fmt.Errorf("SHA256SUMS is\n%s\nwant\n%s", sums, SHA256SUMS()))
	}
	if len(errs) == 0 {
		return nil
	}
	if err := CleanOut(dir); err != nil {
		errs = append(errs, err)
	}
	return errors.Join(errs...)
}

// CleanOut removes every output build.sh writes from dir, so that a failed
// run leaves it as it found it: empty. It reports what it could not remove.
func CleanOut(dir string) error {
	var errs []error
	for _, name := range Outputs() {
		if err := os.Remove(filepath.Join(dir, name)); err != nil && !errors.Is(err, fs.ErrNotExist) {
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

// Options are the command's flags.
type Options struct {
	Out  string // absolute, from ResolveOut
	Jobs int
	Dry  bool
}

// ParseArgs reads the command's flags; wd is the directory bazel run was
// started in, for a relative --out. Anything else on the line is an error.
func ParseArgs(args []string, wd string) (Options, error) {
	fs := flag.NewFlagSet("dfu_util", flag.ContinueOnError)
	out := fs.String("out", "", "a missing or empty directory for dfu-util, its sources, its licences and SHA256SUMS (required)")
	jobs := fs.Int("jobs", 4, "parallel compile jobs, and the container's CPUs")
	dry := fs.Bool("dry_run", false, "print the command, with the script as a here-document; run nothing")
	if err := fs.Parse(args); err != nil {
		return Options{}, err
	}
	if fs.NArg() > 0 {
		return Options{}, fmt.Errorf("unexpected arguments %q; give --out, --jobs or --dry_run", fs.Args())
	}
	if *jobs < 1 {
		return Options{}, fmt.Errorf("--jobs must be 1 or more")
	}
	abs, err := ResolveOut(*out, wd)
	if err != nil {
		return Options{}, err
	}
	return Options{Out: abs, Jobs: *jobs, Dry: *dry}, nil
}

// CheckMount fails if p cannot be a podman -v source: -v splits on ":".
func CheckMount(p string) error {
	if strings.Contains(p, ":") {
		return fmt.Errorf("%q has a \":\", which podman's -v cannot take", p)
	}
	return nil
}

var plainArg = regexp.MustCompile(`^[\w@%+=:,./-]+$`)

// Quote returns argv as one line a POSIX shell reads back as argv.
func Quote(argv []string) string {
	out := make([]string, len(argv))
	for i, a := range argv {
		if plainArg.MatchString(a) {
			out[i] = a
		} else {
			out[i] = "'" + strings.ReplaceAll(a, "'", `'\''`) + "'"
		}
	}
	return strings.Join(out, " ")
}

// caToken stands for the CA copy's directory in DryRun's command; the
// printed script makes the copy itself, in a mktemp directory.
const caToken = "@CA@"

// DryRun returns what --dry_run prints: a script that copies the CA bundle
// bundle into a new temporary directory, creates out, runs podman with
// build.sh as a here-document, and removes the copy. Printing it changes
// nothing on the host.
func DryRun(out, bundle string, jobs int) string {
	cmd := Quote(Command(out, caToken+"/ca.crt", jobs))
	cmd = strings.Replace(cmd, caToken, `"$CA"`, 1)
	return `CA=$(mktemp -d) && cp ` + Quote([]string{bundle}) + ` "$CA/ca.crt" && ` +
		Quote([]string{"mkdir", "-p", out}) + " && " + cmd + " <<'BUILD_SH'\n" +
		strings.TrimSuffix(BuildScript, "\n") + "\nBUILD_SH\n" + `rm -rf "$CA"` + "\n"
}
