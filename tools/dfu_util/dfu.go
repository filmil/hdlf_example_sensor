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
const BinarySHA256 = "5011353cbf7c6c21d5400a2956756c862a6581659253b958478c0003bdb21804"

// LicensesSHA256 is dfu-util-licenses.tar's sha256, as the manifest pins it.
const LicensesSHA256 = "9175386b10b117b598480bf328070e3f9f6ba8cfe6387f4d1e62cbf628099e32"

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

// VerifyOutput checks what the build left in dir against the pins: the
// binary, the licences and both sources. On any mismatch it removes every
// output, so that a failed run leaves dir empty, and returns the error.
func VerifyOutput(dir string) error {
	pins := map[string]string{
		"dfu-util":                  BinarySHA256,
		"dfu-util-licenses.tar":     LicensesSHA256,
		filepath.Base(LibUSB.URL):   LibUSB.SHA256,
		filepath.Base(DfuUtil.URL):  DfuUtil.SHA256,
	}
	var errs []error
	for _, name := range Outputs() {
		want, pinned := pins[name]
		if !pinned {
			continue
		}
		if err := VerifyFile(filepath.Join(dir, name), want); err != nil {
			errs = append(errs, err)
		}
	}
	if len(errs) == 0 {
		return nil
	}
	for _, name := range Outputs() {
		os.Remove(filepath.Join(dir, name))
	}
	return errors.Join(errs...)
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

// DryRun returns what --dry_run prints for out: a command that creates out
// and runs podman with the script as a here-document on its standard input,
// which a shell runs as it is. argv must mount a copy of the CA bundle,
// never the host's file (CopyCABundle).
func DryRun(out string, argv []string) string {
	return Quote([]string{"mkdir", "-p", out}) + " && " + Quote(argv) + " <<'BUILD_SH'\n" + strings.TrimSuffix(BuildScript, "\n") + "\nBUILD_SH\n"
}
