// SPDX-License-Identifier: Apache-2.0

package dfuutil

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/bazelbuild/rules_go/go/runfiles"
)

func readRunfile(t *testing.T, path string) []byte {
	t.Helper()
	p, err := runfiles.Rlocation("_main/" + path)
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

var sha = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Every input is pinned: the image by digest, the packages by snapshot, the
// two downloads by sha256, which the script checks before it unpacks them.
func TestInputsArePinned(t *testing.T) {
	if !regexp.MustCompile(`@sha256:[0-9a-f]{64}$`).MatchString(Image) {
		t.Errorf("image %q is not pinned by digest", Image)
	}
	if !regexp.MustCompile(`^\d{8}T\d{6}Z$`).MatchString(AptSnapshot) {
		t.Errorf("apt snapshot %q", AptSnapshot)
	}
	for _, in := range []Input{LibUSB, DfuUtil} {
		if !strings.HasPrefix(in.URL, "https://") || !sha.MatchString(in.SHA256) {
			t.Errorf("input %+v", in)
		}
	}
	if !sha.MatchString(BinarySHA256) {
		t.Errorf("binary sha256 %q", BinarySHA256)
	}
	for _, want := range []string{
		`fetch "$LIBUSB_URL" "$LIBUSB_SHA256"`,
		`fetch "$DFU_UTIL_URL" "$DFU_UTIL_SHA256"`,
		`sha256sum -c -`,
		`URIs: https://snapshot.ubuntu.com/ubuntu/$APT_SNAPSHOT/`,
		`rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*`,
		`Acquire::https::CaInfo=/host-ca.crt`,
		`--disable-udev`,
		`LDFLAGS="-static"`,
		`dfu-util is not static`,
	} {
		if !strings.Contains(BuildScript, want) {
			t.Errorf("build.sh lacks %q", want)
		}
	}
	if strings.Contains(BuildScript, "archive.ubuntu.com") {
		t.Error("build.sh names the live archive")
	}
	if i, j := strings.Index(BuildScript, "rm -f /etc/apt/sources.list"), strings.Index(BuildScript, "apt-get"); i < 0 || j < i {
		t.Error("build.sh runs apt-get before it replaces the sources")
	}
	if strings.Contains(BuildScript, "| head") {
		t.Error("build.sh pipes into head")
	}
}

// pairs returns the values of flag in argv: "-e", "X=1" gives "X=1".
func pairs(argv []string, flag string) []string {
	var v []string
	for i := 0; i+1 < len(argv); i++ {
		if argv[i] == flag {
			v = append(v, argv[i+1])
		}
	}
	return v
}

// The command passes every input to the container as its own argument, and
// mounts nothing of the host's but the output and the CA bundle.
func TestCommand(t *testing.T) {
	argv := Command("/o", "/ca.crt", 3)
	if got := strings.Join(argv[:4], " "); got != "podman run --rm -i" {
		t.Errorf("command starts %q", got)
	}
	if got := argv[len(argv)-3:]; got[0] != Image || got[1] != "bash" || got[2] != "-s" {
		t.Errorf("command ends %q", got)
	}
	has := func(xs []string, x string) bool {
		for _, y := range xs {
			if y == x {
				return true
			}
		}
		return false
	}
	for _, want := range []string{"--platform=linux/amd64", "--cpus=3"} {
		if !has(argv, want) {
			t.Errorf("command lacks %q: %q", want, argv)
		}
	}
	if v := pairs(argv, "-v"); len(v) != 2 || v[0] != "/o:/out:Z" || v[1] != "/ca.crt:/host-ca.crt:ro,Z" {
		t.Errorf("volumes %q, want only /out and the CA bundle, read-only", v)
	}
	env := pairs(argv, "-e")
	for _, want := range []string{
		"APT_SNAPSHOT=" + AptSnapshot,
		"LIBUSB_URL=" + LibUSB.URL, "LIBUSB_SHA256=" + LibUSB.SHA256,
		"DFU_UTIL_URL=" + DfuUtil.URL, "DFU_UTIL_SHA256=" + DfuUtil.SHA256,
		"JOBS=3",
	} {
		if !has(env, want) {
			t.Errorf("no -e %q in %q", want, env)
		}
	}
	if len(env) != 6 {
		t.Errorf("%d -e arguments, want 6: %q", len(env), env)
	}
}

// The tool builds what //fw:flash runs: MODULE.bazel fetches this sha256
// from the mirror release, and the manifest lists the binary as built from
// dfu-util's source by this tool, with both sources mirrored as downloaded.
func TestMatchesModuleAndManifest(t *testing.T) {
	mod := string(readRunfile(t, "MODULE.bazel"))
	pin := regexp.MustCompile(`name = "dfu_util",\s*executable = True,\s*sha256 = "([0-9a-f]{64})",\s*urls = \["([^"]+)"\]`).FindStringSubmatch(mod)
	if pin == nil {
		t.Fatal("MODULE.bazel has no http_file dfu_util with executable, sha256 and urls")
	}
	if pin[1] != BinarySHA256 {
		t.Errorf("MODULE.bazel pins dfu-util to %s, the tool builds %s", pin[1], BinarySHA256)
	}
	var m struct {
		Repo     string `json:"repo"`
		Releases []struct {
			Tag    string `json:"tag"`
			Notes  string `json:"notes"`
			Assets []struct {
				Name   string `json:"name"`
				SHA256 string `json:"sha256"`
				URL    string `json:"url"`
				Built  *struct {
					Source       string `json:"source"`
					SourceSHA256 string `json:"source_sha256"`
					Script       string `json:"script"`
				} `json:"built"`
			} `json:"assets"`
		} `json:"releases"`
	}
	if err := json.Unmarshal(readRunfile(t, "tools/mirror/manifest.json"), &m); err != nil {
		t.Fatal(err)
	}
	found := map[string]bool{}
	for _, r := range m.Releases {
		if r.Tag != "mirror-dfu-util-0.11" {
			continue
		}
		for _, a := range r.Assets {
			found[a.Name] = true
			switch a.Name {
			case "dfu-util":
				if a.SHA256 != BinarySHA256 {
					t.Errorf("manifest: dfu-util has sha256 %s, the tool %s", a.SHA256, BinarySHA256)
				}
				if a.Built == nil || a.Built.Source != DfuUtil.URL || a.Built.SourceSHA256 != DfuUtil.SHA256 || !strings.Contains(a.Built.Script, "//tools/dfu_util") {
					t.Errorf("manifest: dfu-util is not built from %s by //tools/dfu_util", DfuUtil.URL)
				}
				if want := "https://github.com/" + m.Repo + "/releases/download/" + r.Tag + "/dfu-util"; pin[2] != want {
					t.Errorf("MODULE.bazel fetches %s, the mirror is %s", pin[2], want)
				}
			case "libusb-1.0.30.tar.bz2":
				if a.URL != LibUSB.URL || a.SHA256 != LibUSB.SHA256 {
					t.Errorf("manifest: %s is not %+v", a.Name, LibUSB)
				}
			case "dfu-util-0.11.tar.gz":
				if a.URL != DfuUtil.URL || a.SHA256 != DfuUtil.SHA256 {
					t.Errorf("manifest: %s is not %+v", a.Name, DfuUtil)
				}
			}
		}
		for _, want := range []string{LibUSB.URL, LibUSB.SHA256, DfuUtil.URL, DfuUtil.SHA256, "GPL-2.0-or-later", "LGPL-2.1-or-later"} {
			if !strings.Contains(r.Notes, want) {
				t.Errorf("manifest: the notes of %s do not name %s", r.Tag, want)
			}
		}
	}
	for _, name := range []string{"dfu-util", "libusb-1.0.30.tar.bz2", "dfu-util-0.11.tar.gz", "dfu-util-licenses.tar"} {
		if !found[name] {
			t.Errorf("manifest: no asset %s in mirror-dfu-util-0.11", name)
		}
	}
}

func TestResolveOut(t *testing.T) {
	for _, c := range []struct{ out, wd, want string }{
		{"/tmp/x", "", "/tmp/x"},
		{"/tmp/x/../y", "/w", "/tmp/y"},
		{"x", "/w", "/w/x"},
	} {
		if got, err := ResolveOut(c.out, c.wd); err != nil || got != c.want {
			t.Errorf("ResolveOut(%q, %q) = %q, %v; want %q", c.out, c.wd, got, err, c.want)
		}
	}
	for _, c := range []struct{ out, wd string }{
		{"", "/w"},       // missing
		{"x", ""},        // relative, no working directory
		{"x", "w"},       // relative working directory: podman would take a volume name
		{"/tmp/a:b", ""}, // podman's -v splits on ":"
	} {
		if got, err := ResolveOut(c.out, c.wd); err == nil {
			t.Errorf("ResolveOut(%q, %q) = %q, want an error", c.out, c.wd, got)
		}
	}
}

func TestCheckOut(t *testing.T) {
	d := t.TempDir()
	if err := CheckOut(filepath.Join(d, "missing")); err != nil {
		t.Errorf("a missing directory: %v", err)
	}
	if err := CheckOut(d); err != nil {
		t.Errorf("an empty directory: %v", err)
	}
	if err := os.WriteFile(filepath.Join(d, "old"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := CheckOut(d); err == nil {
		t.Error("a non-empty directory passed")
	}
	// A file where the directory should be: ReadDir fails, and so must this.
	if err := CheckOut(filepath.Join(d, "old")); err == nil {
		t.Error("a file passed as --out")
	}
}

func TestVerifyBinary(t *testing.T) {
	p := filepath.Join(t.TempDir(), "dfu-util")
	if err := os.WriteFile(p, []byte("not the archive"), 0o644); err != nil {
		t.Fatal(err)
	}
	h := sha256.Sum256([]byte("not the archive"))
	err := VerifyBinary(p)
	if err == nil || !strings.Contains(err.Error(), hex.EncodeToString(h[:])) {
		t.Errorf("a wrong binary: %v", err)
	}
	if err := VerifyBinary(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Error("a missing binary passed")
	}
}

func TestCopyCABundle(t *testing.T) {
	d := t.TempDir()
	p, err := CopyCABundle(d)
	if err != nil {
		t.Skipf("no CA bundle in the test's sandbox: %v", err)
	}
	if filepath.Dir(p) != d {
		t.Errorf("the copy %s is not in %s", p, d)
	}
	src, _ := FindCABundle()
	a, _ := os.ReadFile(src)
	b, _ := os.ReadFile(p)
	if len(a) == 0 || string(a) != string(b) {
		t.Error("the copy differs from the bundle")
	}
}

func TestFindCABundle(t *testing.T) {
	// The test's sandbox may have none; when it has one, it is a listed file.
	if p, err := FindCABundle(); err == nil {
		found := false
		for _, c := range CABundles {
			found = found || p == c
		}
		if !found {
			t.Errorf("FindCABundle() = %q, not one of %v", p, CABundles)
		}
	}
}

// --dry_run prints a command a shell runs as it is: quoted arguments, and
// the script as a here-document on standard input.
func TestDryRun(t *testing.T) {
	out := DryRun(Command("/tmp/my out", "/ca.crt", 2))
	first, rest, _ := strings.Cut(out, "\n")
	if !strings.Contains(first, "-v '/tmp/my out:/out:Z'") {
		t.Errorf("the path with a space is not quoted: %s", first)
	}
	if !strings.HasSuffix(first, "bash -s <<'BUILD_SH'") {
		t.Errorf("no here-document: %s", first)
	}
	if rest != strings.TrimSuffix(BuildScript, "\n")+"\nBUILD_SH\n" {
		t.Error("the here-document is not the script")
	}
	if strings.Contains(BuildScript, "\nBUILD_SH\n") {
		t.Error("the script contains the here-document's end marker")
	}
	if got := Quote([]string{"a", "it's", "x y"}); got != `a 'it'\''s' 'x y'` {
		t.Errorf("Quote: %s", got)
	}
}
