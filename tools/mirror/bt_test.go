// SPDX-License-Identifier: Apache-2.0

package mirror

import (
	"bytes"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// fakeBt is bt.hdlfactory.com as nginx serves it: GET for anyone, PUT
// with the publisher login only.
type fakeBt struct {
	mu    sync.Mutex
	files map[string][]byte
	puts  int
}

func (f *fakeBt) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	switch r.Method {
	case http.MethodGet:
		b, ok := f.files[r.URL.Path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Write(b)
	case http.MethodPut:
		if u, p, ok := r.BasicAuth(); !ok || u != BtUser || p != "s3cret" {
			http.Error(w, "no", http.StatusUnauthorized)
			return
		}
		var b bytes.Buffer
		b.ReadFrom(r.Body)
		f.files[r.URL.Path] = b.Bytes()
		f.puts++
		w.WriteHeader(http.StatusCreated)
	default:
		http.Error(w, "no", http.StatusMethodNotAllowed)
	}
}

func btServer(t *testing.T) (*fakeBt, *httptest.Server) {
	t.Helper()
	f := &fakeBt{files: map[string][]byte{}}
	srv := httptest.NewServer(f)
	old := btHost
	btHost = srv.URL + "/"
	t.Cleanup(func() { btHost = old; srv.Close() })
	return f, srv
}

func btFiles(t *testing.T, files map[string]string) []string {
	t.Helper()
	d := t.TempDir()
	var out []string
	for n, b := range files {
		p := filepath.Join(d, n)
		if err := os.WriteFile(p, []byte(b), 0o644); err != nil {
			t.Fatal(err)
		}
		out = append(out, p)
	}
	return out
}

// The same bytes as the Python method that made //third_party/dfu_util's
// .torrent, for a small file: the two agree.
func TestTorrentBytes(t *testing.T) {
	want, _ := hex.DecodeString("6431303a6372656174656420627935313a68646c665f6578616d706c655f73656e736f72202861732072756c65735f6b6963616420746f6f6c732f6d6f64656c73336429343a696e666f64363a6c656e677468693565343a6e616d65353a782e62696e31323a7069656365206c656e677468693130343835373665363a70696563657332303aaaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d65383a75726c2d6c6973746c33333a68747470733a2f2f62742e68646c666163746f72792e636f6d2f742f782e62696e6565")
	if got := Torrent("x.bin", []byte("hello"), "https://bt.hdlfactory.com/t/x.bin"); !bytes.Equal(got, want) {
		t.Errorf("Torrent:\n%q\nwant\n%q", got, want)
	}
}

func TestPublishBtUploadsThenSkips(t *testing.T) {
	f, srv := btServer(t)
	files := btFiles(t, map[string]string{"a.tar": "aaa", "b.tar": "bbbb"})
	var log bytes.Buffer
	if err := PublishBt(srv.Client(), btHost+"p/1/", files, "s3cret", false, &log); err != nil {
		t.Fatal(err)
	}
	if f.puts != 4 {
		t.Errorf("%d PUTs, want 4 (two files, two torrents)", f.puts)
	}
	if got := string(f.files["/p/1/a.tar"]); got != "aaa" {
		t.Errorf("a.tar: %q", got)
	}
	if want := Torrent("b.tar", []byte("bbbb"), btHost+"p/1/b.tar"); !bytes.Equal(f.files["/p/1/b.tar.torrent"], want) {
		t.Errorf("b.tar.torrent is not its torrent")
	}
	if strings.Contains(log.String(), "s3cret") {
		t.Errorf("the log has the password")
	}
	// Again: everything is there with the same bytes, so nothing is PUT,
	// and no password is needed.
	log.Reset()
	if err := PublishBt(srv.Client(), btHost+"p/1/", files, "", false, &log); err != nil {
		t.Fatal(err)
	}
	if f.puts != 4 || strings.Count(log.String(), "already published") != 4 {
		t.Errorf("second run: %d PUTs; log:\n%s", f.puts, log.String())
	}
}

func TestPublishBtStopsOnOtherBytes(t *testing.T) {
	f, srv := btServer(t)
	f.files["/p/1/b.tar"] = []byte("other")
	files := btFiles(t, map[string]string{"a.tar": "aaa", "b.tar": "bbbb"})
	err := PublishBt(srv.Client(), btHost+"p/1/", files, "s3cret", false, &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "b.tar is published with sha256") {
		t.Errorf("err %v, want b.tar published with other bytes", err)
	}
	if f.puts != 0 {
		t.Errorf("%d PUTs before the conflict was reported, want 0", f.puts)
	}
}

func TestPublishBtDryRunAndPassword(t *testing.T) {
	f, srv := btServer(t)
	files := btFiles(t, map[string]string{"a.tar": "aaa"})
	var log bytes.Buffer
	if err := PublishBt(srv.Client(), btHost+"p/1/", files, "", true, &log); err != nil {
		t.Fatal(err)
	}
	if f.puts != 0 || strings.Count(log.String(), "would PUT") != 2 {
		t.Errorf("dry run: %d PUTs; log:\n%s", f.puts, log.String())
	}
	err := PublishBt(srv.Client(), btHost+"p/1/", files, "", false, &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "BT_UPLOAD_PASSWORD") || f.puts != 0 {
		t.Errorf("no password: err %v, %d PUTs", err, f.puts)
	}
	err = PublishBt(srv.Client(), btHost+"p/1/", files, "wrong", false, &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "401") {
		t.Errorf("a wrong password: err %v", err)
	}
}

func TestBtBase(t *testing.T) {
	for _, bad := range []string{"https://example.com/p/", BtHost, BtHost + "p", BtHost + "p/../q/", BtHost + "p//q/", BtHost + "p/?x=1/", "http://bt.hdlfactory.com/p/"} {
		if checkBtBase(bad) == nil {
			t.Errorf("%q accepted", bad)
		}
	}
	for _, good := range []string{BtHost + "rust/1.100.0/", BtHost + "crates/"} {
		if err := checkBtBase(good); err != nil {
			t.Errorf("%q: %v", good, err)
		}
	}
	m := `{"repo": "o/r", "releases": [{"tag": "t", "title": "T", "assets": [{"name": "a", "sha256": "` + strings.Repeat("a", 64) + `", "url": "https://x/a"}], "bt": {"base": "https://example.com/"}}]}`
	if _, err := Parse([]byte(m)); err == nil {
		t.Errorf("a manifest with a bt base off bt.hdlfactory.com parsed")
	}
}

// Mirror --to=bt: only releases with a bt base; the password is needed
// before anything when it uploads; a dry run checks and uploads nothing.
func TestMirrorToBt(t *testing.T) {
	f, srv := btServer(t)
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("library")) }))
	defer up.Close()
	asset := Asset{Name: "lib.tar.gz", SHA256: sum("library"), URL: up.URL + "/lib.tar.gz"}
	m := &Manifest{Repo: "o/r", Releases: []Release{
		{Tag: "gh-only", Title: "G", Assets: []Asset{asset}},
		{Tag: "both", Title: "B", Assets: []Asset{asset}, Bt: &Bt{Base: btHost + "lib/1/"}},
	}}
	opts := func(dry bool, release, password string) MirrorOptions {
		return MirrorOptions{
			Options: Options{Client: srv.Client(), WorkDir: t.TempDir(), Log: &bytes.Buffer{}},
			DryRun:  dry, Release: release, To: "bt", BtPassword: password,
			Run: func(argv []string) (string, error) { t.Errorf("ran %v", argv); return "", nil },
		}
	}
	if err := Mirror(m, opts(false, "", "")); err == nil || !strings.Contains(err.Error(), "BT_UPLOAD_PASSWORD") {
		t.Errorf("no password: %v", err)
	}
	if err := Mirror(m, opts(false, "gh-only", "s3cret")); err == nil || !strings.Contains(err.Error(), "no bt base") {
		t.Errorf("a release without bt: %v", err)
	}
	if err := Mirror(m, opts(true, "", "")); err != nil || f.puts != 0 {
		t.Errorf("dry run: %v, %d PUTs", err, f.puts)
	}
	if err := Mirror(m, opts(false, "", "s3cret")); err != nil {
		t.Fatal(err)
	}
	if string(f.files["/lib/1/lib.tar.gz"]) != "library" || f.puts != 2 {
		t.Errorf("published %v, %d PUTs", f.files, f.puts)
	}
	o := opts(true, "", "")
	o.To = "ftp"
	if err := Mirror(m, o); err == nil {
		t.Errorf("--to=ftp accepted")
	}
}
