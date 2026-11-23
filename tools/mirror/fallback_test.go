// SPDX-License-Identifier: Apache-2.0

package mirror

import (
	"regexp"
	"strings"
	"testing"
)

// rewrites applies a Bazel downloader config's rewrite lines to url, as
// Bazel's UrlRewriterConfig does: lines with the same pattern form one
// group, at the place of the pattern's first line, with their
// replacements in order; each pattern must match the whole URL without
// its scheme; every replacement of every matching group gives a URL, with
// the URL's own scheme added back. $N is group N, as in Java (so $1_ is
// group 1 and "_"). A URL no line matches is fetched as it is.
func rewrites(t *testing.T, cfg, url string) []string {
	t.Helper()
	scheme, bare, ok := strings.Cut(url, "://")
	if !ok {
		t.Fatalf("%s: no scheme", url)
	}
	type group struct {
		re   *regexp.Regexp
		subs []string
	}
	var groups []*group
	byPattern := map[string]*group{}
	for _, line := range strings.Split(cfg, "\n") {
		f := strings.Fields(line)
		if len(f) == 0 || strings.HasPrefix(f[0], "#") {
			continue
		}
		if f[0] != "rewrite" || len(f) != 3 {
			t.Fatalf("bazel_downloader.cfg: a line this test does not know: %q", line)
		}
		g, ok := byPattern[f[1]]
		if !ok {
			g = &group{re: regexp.MustCompile("^(?:" + f[1] + ")$")}
			byPattern[f[1]] = g
			groups = append(groups, g)
		}
		g.subs = append(g.subs, f[2])
	}
	javaGroups := regexp.MustCompile(`\$(\d)`)
	var out []string
	for _, g := range groups {
		m := g.re.FindStringSubmatchIndex(bare)
		if m == nil {
			continue
		}
		for _, sub := range g.subs {
			out = append(out, scheme+"://"+string(g.re.ExpandString(nil, javaGroups.ReplaceAllString(sub, "${$1}"), bare, m)))
		}
	}
	if out == nil {
		out = []string{url}
	}
	return out
}

// TestRewritesLikeBazel checks the emulation itself on made-up configs.
func TestRewritesLikeBazel(t *testing.T) {
	cfg := "rewrite a/(x) m1/$1_\nrewrite b/.* other\nrewrite a/(x) m2/$1\n"
	if got := strings.Join(rewrites(t, cfg, "http://a/x"), " "); got != "http://m1/x_ http://m2/x" {
		t.Errorf("grouped, Java $1_, scheme kept: got %s", got)
	}
	if got := strings.Join(rewrites(t, cfg, "https://a/xy"), " "); got != "https://a/xy" {
		t.Errorf("a partial match rewrote: got %s", got)
	}
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
		switch field("source") {
		case "":
			continue // the workspace's own package
		case "registry+https://github.com/rust-lang/crates.io-index":
		default:
			t.Errorf("%s %s: source %s; only crates.io is mirrored", field("name"), field("version"), field("source"))
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
	// The urls of the call that starts at after: up to the call's closing
	// line, comment lines left out.
	urlsOf := func(after string) []string {
		i := strings.Index(mod, after)
		if i < 0 {
			t.Fatalf("MODULE.bazel has no %q", after)
		}
		end := strings.Index(mod[i:], "\n)")
		if end < 0 {
			t.Fatalf("MODULE.bazel: %q has no closing )", after)
		}
		var call []string
		for _, line := range strings.Split(mod[i:i+end], "\n") {
			if !strings.HasPrefix(strings.TrimSpace(line), "#") {
				call = append(call, line)
			}
		}
		body := strings.Join(call, "\n")
		j := strings.Index(body, "urls = [")
		if j < 0 {
			t.Fatalf("MODULE.bazel: %q has no urls", after)
		}
		k := strings.Index(body[j:], "]")
		if k < 0 {
			t.Fatalf("MODULE.bazel: %q's urls has no ]", after)
		}
		return regexp.MustCompile(`"([^"]+)"`).FindAllString(body[j:j+k], -1)
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
