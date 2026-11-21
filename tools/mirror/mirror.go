// SPDX-License-Identifier: Apache-2.0

// Package mirror checks the archives that MODULE.bazel fetches, and
// uploads them as release assets of this repository: the Rust toolchain's
// tarballs and the firmware's crates.
// It is bazel_rules_em's tools/mirror, ported (issue #14).
//
// The manifest (manifest.json) lists each release and its assets. An asset
// is either:
//
//   - mirrored: the same bytes as an upstream URL, such as a GitLab
//     archive; or
//   - built: made from an upstream source by a script outside this tool,
//     such as dfu-util by //tools/dfu_util.
//
// A dry run gets every upstream file (each mirrored asset, and the source
// of each built asset) and checks its sha256. An upload does the same
// checks, then runs `gh release create` when the release is missing and
// `gh release upload` for its assets.
//
// An upstream file comes from --built_dir when a file there has its name:
// the asset's name for a mirrored asset, the source URL's file name for a
// built asset's source. A build usually leaves them there, and some hosts
// (SourceForge) refuse this tool's downloads. A local file with other
// bytes is an error. Otherwise the file is downloaded from its URL, then
// from each fallback URL in turn while a download fails or has another
// sha256. --built_dir holds one release's files, so it needs --release.
package mirror

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
)

// Manifest is the content of manifest.json.
type Manifest struct {
	// Repo is the GitHub repository of the releases, as OWNER/NAME.
	Repo     string    `json:"repo"`
	Releases []Release `json:"releases"`
}

// Release is one GitHub release and its assets, and where on
// bt.hdlfactory.com they are published too, if anywhere.
type Release struct {
	Tag    string  `json:"tag"`
	Title  string  `json:"title"`
	Notes  string  `json:"notes"`
	Assets []Asset `json:"assets"`
	Bt     *Bt     `json:"bt,omitempty"`
}

// Asset is one file of a release. Exactly one of URL and Built is set.
type Asset struct {
	Name   string `json:"name"`
	SHA256 string `json:"sha256"`
	// URL is the upstream file a mirrored asset copies.
	URL string `json:"url,omitempty"`
	// FallbackURLs serve the same bytes as URL; each is tried, in order,
	// when the download before it fails.
	FallbackURLs []string `json:"fallback_urls,omitempty"`
	Built        *Built   `json:"built,omitempty"`
}

// Built says how a built asset is made.
type Built struct {
	Source string `json:"source"`
	// SourceFallbackURLs serve the same bytes as Source, as FallbackURLs.
	SourceFallbackURLs []string `json:"source_fallback_urls,omitempty"`
	SourceSHA256       string   `json:"source_sha256"`
	Script             string   `json:"script"`
}

var hexSHA = regexp.MustCompile(`^[0-9a-f]{64}$`)

// safeName tells whether n is a plain file name: the tool joins tags and
// asset names to directories.
func safeName(n string) bool {
	return n != "" && n != "." && n != ".." && !strings.ContainsAny(n, "/\\\x00")
}

// Parse reads and checks a manifest.
func Parse(b []byte) (*Manifest, error) {
	var m Manifest
	d := json.NewDecoder(strings.NewReader(string(b)))
	d.DisallowUnknownFields()
	if err := d.Decode(&m); err != nil {
		return nil, fmt.Errorf("manifest: %w", err)
	}
	if _, err := d.Token(); err != io.EOF {
		return nil, fmt.Errorf("manifest: more data after the manifest")
	}
	if len(m.Releases) == 0 {
		return nil, fmt.Errorf("manifest: no releases")
	}
	if !regexp.MustCompile(`^[\w.-]+/[\w.-]+$`).MatchString(m.Repo) {
		return nil, fmt.Errorf("manifest: repo %q: want OWNER/NAME", m.Repo)
	}
	tags := map[string]bool{}
	for _, r := range m.Releases {
		if !safeName(r.Tag) || tags[r.Tag] {
			return nil, fmt.Errorf("manifest: tag %q is repeated, or not a plain file name", r.Tag)
		}
		tags[r.Tag] = true
		if r.Title == "" || len(r.Assets) == 0 {
			return nil, fmt.Errorf("manifest: release %s needs a title and assets", r.Tag)
		}
		if r.Bt != nil {
			if err := checkBtBase(r.Bt.Base); err != nil {
				return nil, fmt.Errorf("manifest: release %s: %w", r.Tag, err)
			}
		}
		names := map[string]bool{}
		for _, a := range r.Assets {
			where := fmt.Sprintf("manifest: %s/%s", r.Tag, a.Name)
			if !safeName(a.Name) || names[a.Name] {
				return nil, fmt.Errorf("%s: the name is repeated, or not a plain file name", where)
			}
			names[a.Name] = true
			if !hexSHA.MatchString(a.SHA256) {
				return nil, fmt.Errorf("%s: sha256 %q: want 64 lowercase hex digits", where, a.SHA256)
			}
			switch {
			case (a.URL == "") == (a.Built == nil):
				return nil, fmt.Errorf("%s: give either url (mirrored) or built", where)
			case a.Built != nil && (a.Built.Source == "" || a.Built.Script == "" || !hexSHA.MatchString(a.Built.SourceSHA256)):
				return nil, fmt.Errorf("%s: built needs source, a source_sha256 of 64 hex digits, and script", where)
			case a.Built != nil && len(a.FallbackURLs) > 0:
				return nil, fmt.Errorf("%s: a built asset's fallbacks are built.source_fallback_urls", where)
			case a.Built != nil && !safeName(sourceName(a.Built.Source)):
				return nil, fmt.Errorf("%s: built.source %q does not end in a file name", where, a.Built.Source)
			}
			fallbacks := a.FallbackURLs
			if a.Built != nil {
				fallbacks = a.Built.SourceFallbackURLs
			}
			for _, u := range fallbacks {
				if u == "" {
					return nil, fmt.Errorf("%s: an empty fallback URL", where)
				}
			}
		}
	}
	return &m, nil
}

// Download fetches url into dir/name and returns its sha256, in hex.
func Download(client *http.Client, url, dir, name string) (string, error) {
	resp, err := client.Get(url)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("GET %s: %s", url, resp.Status)
	}
	f, err := os.Create(filepath.Join(dir, name))
	if err != nil {
		return "", err
	}
	h := sha256.New()
	if _, err := io.Copy(io.MultiWriter(f, h), resp.Body); err != nil {
		f.Close()
		os.Remove(f.Name())
		return "", fmt.Errorf("GET %s: %w", url, err)
	}
	if err := f.Close(); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// sourceName is the file name of a source URL: where --built_dir may hold it.
func sourceName(u string) string {
	if p, err := url.Parse(u); err == nil && p.Path != "" && !strings.HasSuffix(p.Path, "/") {
		return path.Base(p.Path)
	}
	return ""
}

// fetched is one upstream file that fetch got.
type fetched struct {
	path, sum, from string
	// local: path is in o.BuiltDir, so the caller must not remove it.
	local bool
}

// fetch gets one upstream file whose sha256 should be want: from
// o.BuiltDir when it holds local (whatever its sha256, which the caller
// checks), else downloaded into o.WorkDir as name, from each of urls in
// turn until one has the sha256 want. When none has, the error lists
// every failed download and every other sha256.
func fetch(o Options, local string, urls []string, name, want string) (fetched, error) {
	if o.BuiltDir != "" {
		p := filepath.Join(o.BuiltDir, local)
		fi, err := os.Stat(p)
		switch {
		case err == nil && !fi.Mode().IsRegular():
			return fetched{}, fmt.Errorf("%s is not a regular file", p)
		case err == nil:
			sum, err := FileSHA256(p)
			return fetched{path: p, sum: sum, from: p, local: true}, err
		case !errors.Is(err, fs.ErrNotExist):
			return fetched{}, err
		}
	}
	p := filepath.Join(o.WorkDir, name)
	var failed []string
	for _, u := range urls {
		sum, err := Download(o.Client, u, o.WorkDir, name)
		switch {
		case err != nil:
			failed = append(failed, err.Error())
		case sum != want:
			failed = append(failed, fmt.Sprintf("%s has sha256 %s, the manifest says %s", u, sum, want))
		default:
			return fetched{path: p, sum: sum, from: u}, nil
		}
	}
	os.Remove(p)
	return fetched{}, fmt.Errorf("%s", strings.Join(failed, "; "))
}

// FileSHA256 returns the sha256 of the file at p, in hex.
func FileSHA256(p string) (string, error) {
	f, err := os.Open(p)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// Options says what Check does.
type Options struct {
	Client *http.Client
	// WorkDir gets the downloads.
	WorkDir string
	// BuiltDir holds the built assets, by name. Empty: built assets are
	// not checked, only their sources. A mirrored asset or a source found
	// there, by name, is used instead of downloading it.
	BuiltDir string
	// Log gets one line per file checked.
	Log io.Writer
}

// Check gets and checks every upstream file of release r, and the
// built assets in o.BuiltDir. It returns the path of each asset that is
// ready to upload, by name, and an error that lists every mismatch.
func Check(r Release, o Options) (map[string]string, error) {
	ready := map[string]string{}
	var problems []string
	for _, a := range r.Assets {
		if a.URL != "" {
			f, err := fetch(o, a.Name, append([]string{a.URL}, a.FallbackURLs...), a.Name, a.SHA256)
			switch {
			case err != nil:
				problems = append(problems, fmt.Sprintf("%s: %v", a.Name, err))
			case f.sum != a.SHA256:
				problems = append(problems, fmt.Sprintf("%s: %s has sha256 %s, the manifest says %s", a.Name, f.from, f.sum, a.SHA256))
			default:
				fmt.Fprintf(o.Log, "ok %s/%s %s (from %s)\n", r.Tag, a.Name, f.sum, f.from)
				ready[a.Name] = f.path
			}
			continue
		}
		src := a.Name + ".source"
		f, err := fetch(o, sourceName(a.Built.Source), append([]string{a.Built.Source}, a.Built.SourceFallbackURLs...), src, a.Built.SourceSHA256)
		switch {
		case err != nil:
			problems = append(problems, fmt.Sprintf("%s: source: %v", a.Name, err))
		case f.sum != a.Built.SourceSHA256:
			problems = append(problems, fmt.Sprintf("%s: source %s has sha256 %s, the manifest says %s", a.Name, f.from, f.sum, a.Built.SourceSHA256))
		default:
			fmt.Fprintf(o.Log, "ok %s/%s: source %s (from %s)\n", r.Tag, a.Name, f.sum, f.from)
		}
		// Only a download of ours; never a file in --built_dir.
		if f.path != "" && !f.local {
			os.Remove(f.path)
		}
		if o.BuiltDir == "" {
			fmt.Fprintf(o.Log, "-- %s/%s: built by %s; give --built_dir to check and upload it\n", r.Tag, a.Name, a.Built.Script)
			continue
		}
		p := filepath.Join(o.BuiltDir, a.Name)
		got, err := FileSHA256(p)
		switch {
		case err != nil:
			problems = append(problems, fmt.Sprintf("%s: %v", a.Name, err))
		case got != a.SHA256:
			problems = append(problems, fmt.Sprintf("%s: %s has sha256 %s, the manifest says %s", a.Name, p, got, a.SHA256))
		default:
			fmt.Fprintf(o.Log, "ok %s/%s %s (built, from %s)\n", r.Tag, a.Name, got, p)
			ready[a.Name] = p
		}
	}
	if len(problems) > 0 {
		return ready, fmt.Errorf("%s:\n  %s", r.Tag, strings.Join(problems, "\n  "))
	}
	return ready, nil
}

// CreateCommand returns the gh command that creates release r.
func CreateCommand(repo string, r Release) []string {
	return []string{"gh", "release", "create", r.Tag, "--repo", repo, "--title", r.Title, "--notes", r.Notes}
}

// UploadCommand returns the gh command that uploads the given files to
// release r. Without --clobber, gh refuses to replace an asset that is
// already there.
func UploadCommand(repo string, r Release, files []string) []string {
	return append([]string{"gh", "release", "upload", r.Tag, "--repo", repo}, files...)
}

// Quote returns argv as a line a POSIX shell reads back as argv.
func Quote(argv []string) string {
	var out []string
	for _, a := range argv {
		if regexp.MustCompile(`^[\w@%+=:,./-]+$`).MatchString(a) {
			out = append(out, a)
		} else {
			out = append(out, "'"+strings.ReplaceAll(a, "'", `'\''`)+"'")
		}
	}
	return strings.Join(out, " ")
}

// Runner runs a command and returns what it wrote to stderr.
type Runner func(argv []string) (stderr string, err error)

// MirrorOptions says what Mirror does.
type MirrorOptions struct {
	Options
	// DryRun checks and prints the commands, and runs none.
	DryRun bool
	// Release limits the run to one tag; empty is every release.
	Release string
	// Run runs a gh command. Mirror calls it only when DryRun is false.
	Run Runner
	// To is where the files go: "github" (release assets, the default) or
	// "bt" (bt.hdlfactory.com, for releases that name a bt base).
	To string
	// BtPassword is the bt upload password, for To "bt" without DryRun.
	// It goes into the PUTs' login only, never into a log line.
	BtPassword string
}

// Mirror checks every selected release first, each in its own directory
// under o.WorkDir. Only when all of them match does it print, or run, the
// gh commands: `gh release create` for a release that is missing, then
// `gh release upload`.
func Mirror(m *Manifest, o MirrorOptions) error {
	type plan struct {
		r     Release
		files []string
	}
	var plans []plan
	var problems []string
	switch o.To {
	case "", "github":
	case "bt":
		if !o.DryRun && o.BtPassword == "" {
			return fmt.Errorf("$BT_UPLOAD_PASSWORD is not set; nothing checked or uploaded")
		}
	default:
		return fmt.Errorf("--to %q: want github or bt", o.To)
	}
	for _, r := range m.Releases {
		if o.Release != "" && r.Tag != o.Release {
			continue
		}
		if o.To == "bt" && r.Bt == nil {
			if o.Release != "" {
				return fmt.Errorf("release %s names no bt base", r.Tag)
			}
			continue
		}
		ro := o.Options
		ro.WorkDir = filepath.Join(o.WorkDir, r.Tag)
		if err := os.MkdirAll(ro.WorkDir, 0o755); err != nil {
			return err
		}
		ready, err := Check(r, ro)
		if err != nil {
			problems = append(problems, err.Error())
			continue
		}
		p := plan{r: r}
		for _, a := range r.Assets {
			switch f, ok := ready[a.Name]; {
			case ok:
				p.files = append(p.files, f)
			case o.DryRun:
				// Where the upload will look for the built file.
				p.files = append(p.files, filepath.Join("BUILT_DIR", a.Name))
			default:
				problems = append(problems, fmt.Sprintf("%s/%s: built by %s; give --built_dir to upload it", r.Tag, a.Name, a.Built.Script))
			}
		}
		plans = append(plans, p)
	}
	if o.Release != "" && len(plans) == 0 && len(problems) == 0 {
		return fmt.Errorf("no release %q in the manifest", o.Release)
	}
	if len(problems) > 0 {
		return fmt.Errorf("nothing uploaded:\n%s", strings.Join(problems, "\n"))
	}
	if o.To == "bt" {
		if len(plans) == 0 {
			return fmt.Errorf("no release names a bt base")
		}
		for _, p := range plans {
			if o.DryRun {
				for _, f := range p.files {
					if strings.HasPrefix(f, "BUILT_DIR") {
						return fmt.Errorf("%s: give --built_dir, so the built assets can be checked against bt", p.r.Tag)
					}
				}
			}
			if err := PublishBt(o.Client, p.r.Bt.Base, p.files, o.BtPassword, o.DryRun, o.Log); err != nil {
				return fmt.Errorf("%s: %w", p.r.Tag, err)
			}
		}
		if o.DryRun {
			fmt.Fprintln(o.Log, "dry run: every file checked; nothing uploaded")
		}
		return nil
	}
	for _, p := range plans {
		create := CreateCommand(m.Repo, p.r)
		upload := UploadCommand(m.Repo, p.r, p.files)
		if o.DryRun {
			fmt.Fprintln(o.Log, "would run, if the release is missing:", Quote(create))
			fmt.Fprintln(o.Log, "would run:", Quote(upload))
			continue
		}
		stderr, err := o.Run([]string{"gh", "release", "view", p.r.Tag, "--repo", m.Repo})
		switch {
		case err == nil:
		// gh says "release not found"; some versions report the API's 404.
		case strings.Contains(stderr, "release not found") || strings.Contains(stderr, "HTTP 404"):
			if _, err := o.Run(create); err != nil {
				return fmt.Errorf("%s: %w", Quote(create), err)
			}
		default:
			return fmt.Errorf("gh release view %s: %w", p.r.Tag, err)
		}
		if _, err := o.Run(upload); err != nil {
			return fmt.Errorf("%s: %w", Quote(upload), err)
		}
	}
	if o.DryRun {
		fmt.Fprintln(o.Log, "dry run: every file checked matches the manifest; nothing uploaded")
	}
	return nil
}
