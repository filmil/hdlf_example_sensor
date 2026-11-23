// SPDX-License-Identifier: Apache-2.0

package mirror

import (
	"regexp"
	"strings"
	"testing"
)

// rewrites applies a Bazel downloader config's rewrite lines to url, as
// Bazel does: each pattern must match the whole URL without its scheme;
// every line that matches gives a URL, in the file's order, with
// https:// added back. A URL no line matches is fetched as it is.
func rewrites(t *testing.T, cfg, url string) []string {
	t.Helper()
	bare := strings.TrimPrefix(url, "https://")
	var out []string
	for _, line := range strings.Split(cfg, "\n") {
		f := strings.Fields(line)
		if len(f) == 0 || strings.HasPrefix(f[0], "#") {
			continue
		}
		if f[0] != "rewrite" || len(f) != 3 {
			t.Fatalf("bazel_downloader.cfg: a line this test does not know: %q", line)
		}
		re := regexp.MustCompile("^(?:" + f[1] + ")$")
		m := re.FindStringSubmatchIndex(bare)
		if m == nil {
			continue
		}
		out = append(out, "https://"+string(re.ExpandString(nil, f[2], bare, m)))
	}
	if out == nil {
		out = []string{url}
	}
	return out
}

func release(t *testing.T, m *Manifest, tag string) Release {
	t.Helper()
	for _, r := range m.Releases {
		if r.Tag == tag {
			if r.Bt == nil {
				t.Fatalf("%s names no bt base", tag)
			}
			return r
		}
	}
	t.Fatalf("no release %s", tag)
	return Release{}
}

// Every locked crate is fetched from the GitHub mirror, then bt, then
// crates.io, and the first two URLs are assets the manifest mirrors.
func TestDownloaderTriesGitHubThenBtThenCratesIO(t *testing.T) {
	m := readManifest(t)
	cfg, err := readRunfile("bazel_downloader.cfg")
	if err != nil {
		t.Fatal(err)
	}
	lock, err := readRunfile("third_party/crates/Cargo.lock")
	if err != nil {
		t.Fatal(err)
	}
	crates := release(t, m, "mirror-crates-1")
	mirrored := map[string]bool{}
	for _, a := range crates.Assets {
		mirrored[a.Name] = true
	}
	n := 0
	for _, block := range strings.Split(string(lock), "[[package]]")[1:] {
		field := func(k string) string {
			x := regexp.MustCompile(`(?m)^` + k + ` = "([^"]+)"`).FindStringSubmatch(block)
			if x == nil {
				return ""
			}
			return x[1]
		}
		if field("source") == "" {
			continue
		}
		n++
		name, version := field("name"), field("version")
		file := name + "-" + version + ".crate"
		upstream := "https://static.crates.io/crates/" + name + "/" + version + "/download"
		want := []string{
			"https://github.com/" + m.Repo + "/releases/download/" + crates.Tag + "/" + file,
			crates.Bt.Base + file,
			upstream,
		}
		got := rewrites(t, string(cfg), upstream)
		if strings.Join(got, " ") != strings.Join(want, " ") {
			t.Errorf("%s: fetched from\n  %s\nwant\n  %s", file, strings.Join(got, "\n  "), strings.Join(want, "\n  "))
		}
		if !mirrored[file] {
			t.Errorf("%s: not an asset of %s", file, crates.Tag)
		}
	}
	if n == 0 {
		t.Fatal("Cargo.lock has no registry crates")
	}
	// A URL that is no crate is left alone.
	if got := rewrites(t, string(cfg), "https://example.com/x"); len(got) != 1 || got[0] != "https://example.com/x" {
		t.Errorf("an unrelated URL became %v", got)
	}
}

// MODULE.bazel lists bt second, after the GitHub mirror, for the Rust
// toolchain and for dfu-util, at the manifest's bt base.
func TestModuleListsBtSecond(t *testing.T) {
	m := readManifest(t)
	b, err := readRunfile("MODULE.bazel")
	if err != nil {
		t.Fatal(err)
	}
	mod := string(b)
	urlsOf := func(after string) []string {
		i := strings.Index(mod, after)
		if i < 0 {
			t.Fatalf("MODULE.bazel has no %q", after)
		}
		rest := mod[i:]
		j := strings.Index(rest, "urls = [")
		k := strings.Index(rest[j:], "]")
		return regexp.MustCompile(`"([^"]+)"`).FindAllString(rest[j:j+k], -1)
	}
	rust := release(t, m, "mirror-rust-1.100.0")
	want := []string{
		`"https://github.com/` + m.Repo + `/releases/download/` + rust.Tag + `/{}.tar.xz"`,
		`"` + rust.Bt.Base + `{}.tar.xz"`,
		`"https://static.rust-lang.org/dist/{}.tar.xz"`,
	}
	if got := urlsOf("rust.toolchain("); strings.Join(got, " ") != strings.Join(want, " ") {
		t.Errorf("rust.toolchain urls\n  %v\nwant\n  %v", got, want)
	}
	dfu := release(t, m, "mirror-dfu-util-0.11")
	want = []string{
		`"https://github.com/` + m.Repo + `/releases/download/` + dfu.Tag + `/dfu-util"`,
		`"` + dfu.Bt.Base + `dfu-util"`,
	}
	if got := urlsOf(`name = "dfu_util"`); strings.Join(got, " ") != strings.Join(want, " ") {
		t.Errorf("dfu_util urls\n  %v\nwant\n  %v", got, want)
	}
}
