// SPDX-License-Identifier: Apache-2.0

package mirror

import (
	"regexp"
	"sort"
	"strings"
	"testing"
)

const (
	rustTag   = "mirror-rust-1.100.0"
	crateTags = "mirror-crates-"
)

func assets(t *testing.T, m *Manifest, match func(tag string) bool) map[string]Asset {
	t.Helper()
	out := map[string]Asset{}
	for _, r := range m.Releases {
		if !match(r.Tag) {
			continue
		}
		for _, a := range r.Assets {
			out[a.Name] = a
		}
	}
	return out
}

func keys[V any](m map[string]V) []string {
	var k []string
	for x := range m {
		k = append(k, x)
	}
	sort.Strings(k)
	return k
}

// The release mirror-rust-1.100.0 holds exactly the tarballs MODULE.bazel's
// rust.toolchain pins, with the same sha256, each copied from
// static.rust-lang.org; and the mirror is the toolchain's first URL.
func TestManifestMatchesModule(t *testing.T) {
	m := readManifest(t)
	b, err := readRunfile("MODULE.bazel")
	if err != nil {
		t.Fatal(err)
	}
	src := string(b)
	pinned := map[string]string{}
	for _, x := range regexp.MustCompile(`"((?:rustc|cargo|clippy|rustfmt|llvm-tools|rust-std)-[^"]+)": "([0-9a-f]{64})"`).FindAllStringSubmatch(src, -1) {
		pinned[x[1]+".tar.xz"] = x[2]
	}
	if len(pinned) == 0 {
		t.Fatal("MODULE.bazel pins no Rust tarballs")
	}
	first := regexp.MustCompile(`urls = \[\s*"([^"]+)"`).FindStringSubmatch(src)
	want := "https://github.com/" + m.Repo + "/releases/download/" + rustTag + "/{}.tar.xz"
	if first == nil || first[1] != want {
		t.Errorf("the toolchain's first URL is %v, want %s", first, want)
	}
	got := assets(t, m, func(tag string) bool { return tag == rustTag })
	if g, p := keys(got), keys(pinned); strings.Join(g, " ") != strings.Join(p, " ") {
		t.Fatalf("release %s has\n  %v\nMODULE.bazel pins\n  %v", rustTag, g, p)
	}
	for name, sha := range pinned {
		a := got[name]
		if a.SHA256 != sha {
			t.Errorf("%s: the manifest has sha256 %s, MODULE.bazel %s", name, a.SHA256, sha)
		}
		if u := "https://static.rust-lang.org/dist/" + name; a.URL != u {
			t.Errorf("%s: the manifest copies %s, want %s", name, a.URL, u)
		}
	}
}

// The releases mirror-crates-* hold exactly the registry crates of
// fw/Cargo.lock, with Cargo.lock's checksums, each copied from crates.io.
func TestManifestMatchesCargoLock(t *testing.T) {
	m := readManifest(t)
	b, err := readRunfile("fw/Cargo.lock")
	if err != nil {
		t.Fatal(err)
	}
	locked := map[string]string{}
	url := map[string]string{}
	for _, block := range strings.Split(string(b), "[[package]]")[1:] {
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
		name := field("name") + "-" + field("version") + ".crate"
		locked[name] = field("checksum")
		url[name] = "https://static.crates.io/crates/" + field("name") + "/" + field("version") + "/download"
	}
	if len(locked) == 0 {
		t.Fatal("fw/Cargo.lock has no registry crates")
	}
	got := assets(t, m, func(tag string) bool { return strings.HasPrefix(tag, crateTags) })
	for _, name := range keys(locked) {
		a, ok := got[name]
		switch {
		case !ok:
			t.Errorf("%s: in Cargo.lock, not mirrored", name)
		case a.SHA256 != locked[name]:
			t.Errorf("%s: the manifest has sha256 %s, Cargo.lock %s", name, a.SHA256, locked[name])
		case a.URL != url[name]:
			t.Errorf("%s: the manifest copies %s, want %s", name, a.URL, url[name])
		}
	}
	for _, name := range keys(got) {
		if _, ok := locked[name]; !ok {
			t.Errorf("%s: mirrored, not in Cargo.lock", name)
		}
	}
}

// crate_universe fetches only from static.crates.io; the downloader config
// rewrites each crate's URL to every mirror-crates-* release first, then
// crates.io. Bazel checks the sha256 whichever URL answers.
func TestDownloaderConfigNamesEveryCrateRelease(t *testing.T) {
	m := readManifest(t)
	b, err := readRunfile("bazel_downloader.cfg")
	if err != nil {
		t.Fatal(err)
	}
	cfg := string(b)
	from := `static.crates.io/crates/([^/]+)/([^/]+)/download`
	n := 0
	for _, r := range m.Releases {
		if !strings.HasPrefix(r.Tag, crateTags) {
			continue
		}
		n++
		line := "rewrite " + from + " github.com/" + m.Repo + "/releases/download/" + r.Tag + "/$1-$2.crate"
		if !strings.Contains(cfg, line+"\n") {
			t.Errorf("bazel_downloader.cfg lacks the line\n  %s", line)
		}
	}
	if n == 0 {
		t.Error("the manifest has no mirror-crates-* release")
	}
	// crates.io last, so a crate not yet mirrored still downloads.
	if !strings.HasSuffix(strings.TrimSpace(cfg), "rewrite ("+`static.crates.io/crates/.*`+") $1") {
		t.Error("bazel_downloader.cfg must end with crates.io itself: rewrite (static.crates.io/crates/.*) $1")
	}
}
