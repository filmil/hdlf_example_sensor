// SPDX-License-Identifier: Apache-2.0

package dfuutil

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
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
	for _, in := range append([]Input{LibUSB, DfuUtil}, MuslSource...) {
		if !strings.HasPrefix(in.URL, "https://") || !sha.MatchString(in.SHA256) {
			t.Errorf("input %+v", in)
		}
	}
	if !sha.MatchString(BinarySHA256) {
		t.Errorf("binary sha256 %q", BinarySHA256)
	}
	for _, want := range []string{
		`fetch "$LIBUSB_URL" "$LIBUSB_SHA256"`,
		`fetch "$DFU_UTIL_URL" "$DFU_UTIL_SHA256" "/work/$DFU" "${DFU_FALLBACKS[@]}"`,
		`fetch "$MUSL_ORIG_URL" "$MUSL_ORIG_SHA256"`,
		`fetch "$MUSL_DEBIAN_URL" "$MUSL_DEBIAN_SHA256"`,
		`sha256sum -c -`,
		`URIs: https://snapshot.ubuntu.com/ubuntu/$APT_SNAPSHOT/`,
		`rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*`,
		`Acquire::https::CaInfo=/host-ca.crt`,
		`--disable-udev`,
		`LDFLAGS="-static"`,
		`export CC=musl-gcc`,
		`musl-tools`,
		`/usr/share/doc/musl/copyright`,
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
		"DFU_UTIL_FALLBACK_URLS=" + strings.Join(DfuUtil.Fallbacks, " "),
		"MUSL_ORIG_URL=" + MuslSource[0].URL, "MUSL_ORIG_SHA256=" + MuslSource[0].SHA256,
		"MUSL_DEBIAN_URL=" + MuslSource[1].URL, "MUSL_DEBIAN_SHA256=" + MuslSource[1].SHA256,
		"JOBS=3",
	} {
		if !has(env, want) {
			t.Errorf("no -e %q in %q", want, env)
		}
	}
	if len(env) != 11 {
		t.Errorf("%d -e arguments, want 11: %q", len(env), env)
	}
}

// The tool builds what //fw:flash runs: MODULE.bazel fetches this sha256
// from the mirror release, and the manifest lists the binary as built from
// dfu-util's source by this tool, with both sources mirrored as downloaded.
func TestMatchesModuleAndManifest(t *testing.T) {
	mod := string(readRunfile(t, "MODULE.bazel"))
	// urls lists the GitHub mirror first (pin[2]); tools/mirror's
	// fallback_test checks the rest of the list.
	pin := regexp.MustCompile(`name = "dfu_util",\s*executable = True,\s*sha256 = "([0-9a-f]{64})",\s*urls = \[\s*"([^"]+)"`).FindStringSubmatch(mod)
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
				Name         string   `json:"name"`
				SHA256       string   `json:"sha256"`
				URL          string   `json:"url"`
				FallbackURLs []string `json:"fallback_urls"`
				Built        *struct {
					Source             string   `json:"source"`
					SourceFallbackURLs []string `json:"source_fallback_urls"`
					SourceSHA256       string   `json:"source_sha256"`
					Script             string   `json:"script"`
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
				if a.Built == nil || a.Built.Source != DfuUtil.URL || strings.Join(a.Built.SourceFallbackURLs, " ") != strings.Join(DfuUtil.Fallbacks, " ") ||
					a.Built.SourceSHA256 != DfuUtil.SHA256 || !strings.Contains(a.Built.Script, "//tools/dfu_util") {
					t.Errorf("manifest: dfu-util is not built from %s by //tools/dfu_util", DfuUtil.URL)
				}
				if want := "https://github.com/" + m.Repo + "/releases/download/" + r.Tag + "/dfu-util"; pin[2] != want {
					t.Errorf("MODULE.bazel fetches %s, the mirror is %s", pin[2], want)
				}
			case "dfu-util-licenses.tar":
				if a.SHA256 != LicensesSHA256 {
					t.Errorf("manifest: the licences have sha256 %s, the tool %s", a.SHA256, LicensesSHA256)
				}
				if a.Built == nil || !strings.Contains(a.Built.Script, "//tools/dfu_util") || a.Built.Source != DfuUtil.URL ||
					strings.Join(a.Built.SourceFallbackURLs, " ") != strings.Join(DfuUtil.Fallbacks, " ") || a.Built.SourceSHA256 != DfuUtil.SHA256 {
					t.Errorf("manifest: the licences are not built from %+v by //tools/dfu_util", DfuUtil)
				}
			case "musl_1.2.5.orig.tar.gz", "musl_1.2.5-3build1.debian.tar.xz":
				ok := false
				for _, in := range MuslSource {
					ok = ok || (filepath.Base(in.URL) == a.Name && a.URL == in.URL && a.SHA256 == in.SHA256)
				}
				if !ok {
					t.Errorf("manifest: %s is not one of %+v", a.Name, MuslSource)
				}
			case "libusb-1.0.30.tar.bz2":
				if a.URL != LibUSB.URL || a.SHA256 != LibUSB.SHA256 {
					t.Errorf("manifest: %s is not %+v", a.Name, LibUSB)
				}
			case "dfu-util-0.11.tar.gz":
				if a.URL != DfuUtil.URL || strings.Join(a.FallbackURLs, " ") != strings.Join(DfuUtil.Fallbacks, " ") || a.SHA256 != DfuUtil.SHA256 {
					t.Errorf("manifest: %s is not %+v", a.Name, DfuUtil)
				}
			}
		}
		// The notes name SourceForge, the project's own URL, not our copy:
		// a release is permanent, and our copy may not be published yet.
		for _, want := range []string{LibUSB.URL, LibUSB.SHA256, DfuUtil.Fallbacks[0], DfuUtil.SHA256, AptSnapshot, "GPL-2.0-or-later", "LGPL-2.1-or-later", "musl MIT"} {
			if !strings.Contains(r.Notes, want) {
				t.Errorf("manifest: the notes of %s do not name %s", r.Tag, want)
			}
		}
	}
	for _, name := range []string{"dfu-util", "libusb-1.0.30.tar.bz2", "dfu-util-0.11.tar.gz", "dfu-util-licenses.tar",
		"musl_1.2.5.orig.tar.gz", "musl_1.2.5-3build1.debian.tar.xz"} {
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

func TestVerifyFile(t *testing.T) {
	p := filepath.Join(t.TempDir(), "dfu-util")
	if err := os.WriteFile(p, []byte("not the binary"), 0o644); err != nil {
		t.Fatal(err)
	}
	h := sha256.Sum256([]byte("not the binary"))
	got := hex.EncodeToString(h[:])
	if err := VerifyFile(p, got); err != nil {
		t.Errorf("the matching sha256: %v", err)
	}
	if err := VerifyFile(p, BinarySHA256); err == nil || !strings.Contains(err.Error(), got) {
		t.Errorf("a wrong file: %v", err)
	}
	if err := VerifyFile(filepath.Join(t.TempDir(), "missing"), got); err == nil {
		t.Error("a missing file passed")
	}
}

// A run whose output does not match the pins leaves --out empty.
func TestVerifyOutputEmptiesOnMismatch(t *testing.T) {
	d := t.TempDir()
	for _, name := range Outputs() {
		if err := os.WriteFile(filepath.Join(d, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := VerifyOutput(d); err == nil {
		t.Fatal("wrong outputs passed")
	}
	if left, _ := os.ReadDir(d); len(left) != 0 {
		t.Errorf("--out still holds %d files", len(left))
	}
}

func TestOutputsUseUpstreamNames(t *testing.T) {
	want := []string{"dfu-util", "libusb-1.0.30.tar.bz2", "dfu-util-0.11.tar.gz", "dfu-util-licenses.tar",
		"musl_1.2.5.orig.tar.gz", "musl_1.2.5-3build1.debian.tar.xz", "SHA256SUMS"}
	if got := strings.Join(Outputs(), " "); got != strings.Join(want, " ") {
		t.Errorf("Outputs() = %s", got)
	}
	for _, want := range []string{`LIBUSB=$(basename "$LIBUSB_URL")`, `DFU=$(basename "$DFU_UTIL_URL")`} {
		if !strings.Contains(BuildScript, want) {
			t.Errorf("build.sh lacks %q", want)
		}
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
// --dry_run prints a script a shell runs as it is, and printing it changes
// nothing: the script makes, mounts and removes its own CA copy.
func TestDryRun(t *testing.T) {
	out := DryRun("/tmp/my out", "/etc/ssl/certs/ca-certificates.crt", 2)
	lines := strings.Split(out, "\n")
	first := lines[0]
	for _, want := range []string{
		`CA=$(mktemp -d) && cp /etc/ssl/certs/ca-certificates.crt "$CA/ca.crt" && `,
		`mkdir -p '/tmp/my out' && podman run`,
		`-v '/tmp/my out:/out:Z'`,
		`-v "$CA"/ca.crt:/host-ca.crt:ro,Z`,
	} {
		if !strings.Contains(first, want) {
			t.Errorf("the first line lacks %q:\n%s", want, first)
		}
	}
	if !strings.HasSuffix(first, "bash -s <<'BUILD_SH'") {
		t.Errorf("no here-document: %s", first)
	}
	if !strings.HasSuffix(out, "\nBUILD_SH\nrm -rf \"$CA\"\n") {
		t.Errorf("the copy is not removed after: ...%s", out[len(out)-40:])
	}
	if !strings.Contains(out, strings.TrimSuffix(BuildScript, "\n")+"\nBUILD_SH\n") {
		t.Error("the here-document is not the script")
	}
	if strings.Contains(BuildScript, "\nBUILD_SH\n") {
		t.Error("the script contains the here-document's end marker")
	}
	if strings.Contains(first, "/etc/ssl/certs/ca-certificates.crt:") {
		t.Error("the command mounts the host's CA bundle")
	}
	if got := Quote([]string{"a", "it's", "x y"}); got != `a 'it'\''s' 'x y'` {
		t.Errorf("Quote: %s", got)
	}
}

func TestParseArgs(t *testing.T) {
	o, err := ParseArgs([]string{"--out=x", "--jobs=3", "--dry_run"}, "/w")
	if err != nil || o != (Options{Out: "/w/x", Jobs: 3, Dry: true}) {
		t.Errorf("ParseArgs = %+v, %v", o, err)
	}
	o, err = ParseArgs([]string{"--out=/o"}, "")
	if err != nil || o != (Options{Out: "/o", Jobs: 4}) {
		t.Errorf("defaults: %+v, %v", o, err)
	}
	for _, args := range [][]string{
		{},                       // no --out
		{"--out=/o", "extra"},    // a stray argument
		{"--out=/o", "--jobs=0"}, // no jobs
		{"--out=/o", "--bogus"},  // an unknown flag
		{"--out=/a:b"},           // a ":" podman cannot mount
	} {
		if o, err := ParseArgs(args, "/w"); err == nil {
			t.Errorf("ParseArgs(%q) = %+v, want an error", args, o)
		}
	}
}

func TestCheckMount(t *testing.T) {
	if err := CheckMount("/tmp/dfu-util-1/ca.crt"); err != nil {
		t.Error(err)
	}
	if err := CheckMount("/tmp/a:b/ca.crt"); err == nil {
		t.Error("a path with a colon passed")
	}
}

// SHA256SUMS must match line by line, and a wrong one empties --out too.
func TestVerifyOutputChecksSHA256SUMS(t *testing.T) {
	want := SHA256SUMS()
	if strings.Count(want, "\n") != 6 || !strings.HasPrefix(want, BinarySHA256+"  dfu-util\n") {
		t.Errorf("SHA256SUMS() = %q", want)
	}
	d := t.TempDir()
	if err := os.WriteFile(filepath.Join(d, "SHA256SUMS"), []byte("wrong\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	err := VerifyOutput(d)
	if err == nil || !strings.Contains(err.Error(), "SHA256SUMS is") {
		t.Errorf("a wrong SHA256SUMS: %v", err)
	}
	if left, _ := os.ReadDir(d); len(left) != 0 {
		t.Errorf("--out still holds %d files", len(left))
	}
}

func TestCleanOut(t *testing.T) {
	d := t.TempDir()
	keep := filepath.Join(d, "not-an-output")
	for _, name := range append(Outputs()[:2], "not-an-output") {
		if err := os.WriteFile(filepath.Join(d, name), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := CleanOut(d); err != nil {
		t.Errorf("CleanOut: %v", err)
	}
	if _, err := os.Stat(keep); err != nil {
		t.Error("CleanOut removed a file it did not write")
	}
	if left, _ := os.ReadDir(d); len(left) != 1 {
		t.Errorf("%d files left, want 1", len(left))
	}
}

// The .torrent published beside DfuUtil.URL is bt.hdlfactory.com's kind:
// one file, 1 MiB pieces, no tracker, and the file's URL as its web seed.
// Its sha256 is pinned, and third_party/dfu_util/README.md's publish step names it.
func TestTorrent(t *testing.T) {
	raw := readRunfile(t, "third_party/dfu_util/dfu-util-0.11.tar.gz.torrent")
	if got := fmt.Sprintf("%x", sha256.Sum256(raw)); got != DfuUtilTorrentSHA256 {
		t.Errorf("the .torrent has sha256 %s, DfuUtilTorrentSHA256 is %s", got, DfuUtilTorrentSHA256)
	}
	if readme := string(readRunfile(t, "third_party/dfu_util/README.md")); strings.Count(readme, DfuUtilTorrentSHA256) < 2 || strings.Count(readme, DfuUtil.SHA256) < 2 {
		t.Errorf("third_party/dfu_util/README.md's publish step and check do not name the pinned sha256s")
	}
	v, rest, err := bdecode(raw)
	if err != nil || len(rest) != 0 {
		t.Fatalf("the .torrent is not one bencoded value: %v, %d bytes after it", err, len(rest))
	}
	top, _ := v.(map[string]any)
	info, _ := top["info"].(map[string]any)
	if info == nil {
		t.Fatal("the .torrent has no info")
	}
	for k := range top {
		if k != "created by" && k != "info" && k != "url-list" {
			t.Errorf("the .torrent has %q (a tracker?)", k)
		}
	}
	pieces, _ := info["pieces"].(string)
	for _, c := range []struct {
		what      string
		got, want any
	}{
		{"name", info["name"], filepath.Base(DfuUtil.URL)},
		{"length", info["length"], int64(DfuUtilSize)},
		{"piece length", info["piece length"], int64(1 << 20)},
		{"pieces", len(pieces), 20 * ((DfuUtilSize + 1<<20 - 1) >> 20)},
		{"url-list", fmt.Sprint(top["url-list"]), fmt.Sprint([]any{DfuUtil.URL})},
	} {
		if c.got != c.want {
			t.Errorf("the .torrent's %s is %v, want %v", c.what, c.got, c.want)
		}
	}
}

// bdecode decodes one bencoded value: a string, an int64, a []any or a
// map[string]any, and returns what follows it.
func bdecode(b []byte) (any, []byte, error) {
	if len(b) == 0 {
		return nil, nil, fmt.Errorf("unexpected end")
	}
	switch c := b[0]; {
	case c == 'i':
		e := bytes.IndexByte(b, 'e')
		if e < 0 {
			return nil, nil, fmt.Errorf("unterminated integer")
		}
		n, err := strconv.ParseInt(string(b[1:e]), 10, 64)
		return n, b[e+1:], err
	case c == 'l' || c == 'd':
		var list []any
		dict := map[string]any{}
		rest := b[1:]
		for len(rest) > 0 && rest[0] != 'e' {
			var k, v any
			var err error
			if c == 'd' {
				if k, rest, err = bdecode(rest); err != nil {
					return nil, nil, err
				}
			}
			if v, rest, err = bdecode(rest); err != nil {
				return nil, nil, err
			}
			if c == 'd' {
				ks, ok := k.(string)
				if !ok {
					return nil, nil, fmt.Errorf("a non-string key")
				}
				dict[ks] = v
			} else {
				list = append(list, v)
			}
		}
		if len(rest) == 0 {
			return nil, nil, fmt.Errorf("unterminated list or dictionary")
		}
		if c == 'd' {
			return dict, rest[1:], nil
		}
		return list, rest[1:], nil
	case c >= '0' && c <= '9':
		colon := bytes.IndexByte(b, ':')
		if colon < 0 {
			return nil, nil, fmt.Errorf("a string without a length")
		}
		n, err := strconv.Atoi(string(b[:colon]))
		if err != nil || n < 0 || colon+1+n > len(b) {
			return nil, nil, fmt.Errorf("a bad string length")
		}
		return string(b[colon+1 : colon+1+n]), b[colon+1+n:], nil
	}
	return nil, nil, fmt.Errorf("unexpected %q", b[0])
}
