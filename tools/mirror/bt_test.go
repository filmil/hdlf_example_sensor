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
// with the publisher login only. fail answers a path with a status;
// corrupt stores other bytes than a PUT sent.
type fakeBt struct {
	mu      sync.Mutex
	files   map[string][]byte
	puts    int
	fail    map[string]int
	corrupt bool
}

func (f *fakeBt) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if code, ok := f.fail[r.URL.Path]; ok {
		if code >= 300 && code < 400 {
			w.Header().Set("Location", "/elsewhere")
		}
		w.WriteHeader(code)
		return
	}
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
		if f.corrupt {
			b.WriteString("!")
		}
		f.files[r.URL.Path] = b.Bytes()
		f.puts++
		w.WriteHeader(http.StatusCreated)
	default:
		http.Error(w, "no", http.StatusMethodNotAllowed)
	}
}

func btServer(t *testing.T) (*fakeBt, *httptest.Server, string) {
	t.Helper()
	f := &fakeBt{files: map[string][]byte{}, fail: map[string]int{}}
	srv := httptest.NewServer(f)
	t.Cleanup(srv.Close)
	return f, srv, srv.URL + "/"
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

func gen(n int) []byte {
	b := make([]byte, n)
	for i := range b {
		b[i] = byte(i*7 + 3)
	}
	return b
}

// The same bytes as the Python method that made //third_party/dfu_util's
// .torrent: a tiny file, an empty one, exactly one piece, and three
// pieces, the last one short. Torrent (in memory) and torrentOf (from
// disk) agree.
func TestTorrentBytes(t *testing.T) {
	for _, c := range []struct {
		name string
		data []byte
		want string
	}{
		{"hello", []byte("hello"), "6431303a6372656174656420627935313a68646c665f6578616d706c655f73656e736f72202861732072756c65735f6b6963616420746f6f6c732f6d6f64656c73336429343a696e666f64363a6c656e677468693565343a6e616d65353a782e62696e31323a7069656365206c656e677468693130343835373665363a70696563657332303aaaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d65383a75726c2d6c6973746c33333a68747470733a2f2f62742e68646c666163746f72792e636f6d2f742f782e62696e6565"},
		{"empty", gen(0), "6431303a6372656174656420627935313a68646c665f6578616d706c655f73656e736f72202861732072756c65735f6b6963616420746f6f6c732f6d6f64656c73336429343a696e666f64363a6c656e677468693065343a6e616d65353a782e62696e31323a7069656365206c656e677468693130343835373665363a706965636573303a65383a75726c2d6c6973746c33333a68747470733a2f2f62742e68646c666163746f72792e636f6d2f742f782e62696e6565"},
		{"one_piece", gen(PieceLength), "6431303a6372656174656420627935313a68646c665f6578616d706c655f73656e736f72202861732072756c65735f6b6963616420746f6f6c732f6d6f64656c73336429343a696e666f64363a6c656e677468693130343835373665343a6e616d65353a782e62696e31323a7069656365206c656e677468693130343835373665363a70696563657332303a9d4a07b141606cf1c54373230e895e684c65446065383a75726c2d6c6973746c33333a68747470733a2f2f62742e68646c666163746f72792e636f6d2f742f782e62696e6565"},
		{"three_pieces", gen(2*PieceLength + PieceLength/2), "6431303a6372656174656420627935313a68646c665f6578616d706c655f73656e736f72202861732072756c65735f6b6963616420746f6f6c732f6d6f64656c73336429343a696e666f64363a6c656e677468693236323134343065343a6e616d65353a782e62696e31323a7069656365206c656e677468693130343835373665363a70696563657336303a9d4a07b141606cf1c54373230e895e684c6544609d4a07b141606cf1c54373230e895e684c65446047fb70891f70c913703d2c4e16688b846a8464a365383a75726c2d6c6973746c33333a68747470733a2f2f62742e68646c666163746f72792e636f6d2f742f782e62696e6565"},
	} {
		want, _ := hex.DecodeString(c.want)
		u := "https://bt.hdlfactory.com/t/x.bin"
		if got := Torrent("x.bin", c.data, u); !bytes.Equal(got, want) {
			t.Errorf("%s: Torrent:\n%q\nwant\n%q", c.name, got, want)
		}
		p := filepath.Join(t.TempDir(), "x.bin")
		os.WriteFile(p, c.data, 0o644)
		got, size, sum, err := torrentOf(p, "x.bin", u)
		if err != nil || !bytes.Equal(got, want) || size != int64(len(c.data)) || sum != sha(c.data) {
			t.Errorf("%s: torrentOf: %v, size %d, sha256 %s", c.name, err, size, sum)
		}
	}
}

func plan(t *testing.T, srv *httptest.Server, host, base string, files []string) ([]BtUpload, error) {
	t.Helper()
	return PlanBt(srv.Client(), host, base, files, &bytes.Buffer{})
}

func TestBtUploadsThenSkips(t *testing.T) {
	f, srv, host := btServer(t)
	files := btFiles(t, map[string]string{"a.tar": "aaa", "b c.tar": "bbbb"})
	up, err := plan(t, srv, host, host+"p/1/", files)
	if err != nil || len(up) != 4 {
		t.Fatalf("plan: %d uploads, %v", len(up), err)
	}
	var log bytes.Buffer
	if err := UploadBt(srv.Client(), up, "s3cret", &log); err != nil {
		t.Fatal(err)
	}
	if string(f.files["/p/1/a.tar"]) != "aaa" {
		t.Errorf("a.tar: %q", f.files["/p/1/a.tar"])
	}
	// A name with a space is escaped in the URL, and in the torrent.
	want := Torrent("b c.tar", []byte("bbbb"), host+"p/1/b%20c.tar")
	if !bytes.Equal(f.files["/p/1/b c.tar.torrent"], want) {
		t.Errorf("b c.tar.torrent is not its torrent")
	}
	if strings.Contains(log.String(), "s3cret") {
		t.Errorf("the log has the password")
	}
	// Again: everything is there with the same bytes.
	if up, err := plan(t, srv, host, host+"p/1/", files); err != nil || len(up) != 0 {
		t.Errorf("second plan: %d uploads, %v", len(up), err)
	}
	// Only the torrent missing: only it is planned.
	delete(f.files, "/p/1/a.tar.torrent")
	if up, err := plan(t, srv, host, host+"p/1/", files); err != nil || len(up) != 1 || !strings.HasSuffix(up[0].URL, "a.tar.torrent") {
		t.Errorf("torrent missing: %v, %v", up, err)
	}
}

func TestBtPlanErrors(t *testing.T) {
	f, srv, host := btServer(t)
	f.files["/p/1/b.tar"] = []byte("other")
	files := btFiles(t, map[string]string{"a.tar": "aaa", "b.tar": "bbbb"})
	if _, err := plan(t, srv, host, host+"p/1/", files); err == nil || !strings.Contains(err.Error(), "b.tar is published with sha256") {
		t.Errorf("other bytes: %v", err)
	}
	f.fail["/p/2/a.tar"] = http.StatusInternalServerError
	if _, err := plan(t, srv, host, host+"p/2/", files[:1]); err == nil || !strings.Contains(err.Error(), "500") {
		t.Errorf("a 500: %v", err)
	}
	f.fail["/p/3/a.tar"] = http.StatusFound
	if _, err := plan(t, srv, host, host+"p/3/", files[:1]); err == nil || !strings.Contains(err.Error(), "302") {
		t.Errorf("a redirect is followed: %v", err)
	}
	// a.tar and a.tar.torrent as assets: two files for one URL.
	clash := btFiles(t, map[string]string{"a.tar": "a", "a.tar.torrent": "x"})
	if _, err := plan(t, srv, host, host+"p/4/", clash); err == nil || !strings.Contains(err.Error(), "two files") {
		t.Errorf("a clash: %v", err)
	}
	if f.puts != 0 {
		t.Errorf("%d PUTs while planning", f.puts)
	}
}

func TestBtUploadErrors(t *testing.T) {
	f, srv, host := btServer(t)
	files := btFiles(t, map[string]string{"a.tar": "aaa"})
	up, err := plan(t, srv, host, host+"p/1/", files)
	if err != nil {
		t.Fatal(err)
	}
	if err := UploadBt(srv.Client(), up, "", &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "BT_UPLOAD_PASSWORD") || f.puts != 0 {
		t.Errorf("no password: %v, %d PUTs", err, f.puts)
	}
	if err := UploadBt(srv.Client(), up, "wrong", &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "401") {
		t.Errorf("a wrong password: %v", err)
	}
	f.corrupt = true
	if err := UploadBt(srv.Client(), up, "s3cret", &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "after the upload") {
		t.Errorf("bytes changed on the server: %v", err)
	}
}

func TestBtBase(t *testing.T) {
	for _, bad := range []string{"https://example.com/p/", BtHost, BtHost + "p", BtHost + "p/../q/", BtHost + "./p/", BtHost + "p//q/",
		BtHost + "p/?x=1/", BtHost + "a b/", BtHost + "a\\b/", BtHost + "P/", "http://bt.hdlfactory.com/p/"} {
		if checkBtBase(bad, BtHost) == nil {
			t.Errorf("%q accepted", bad)
		}
	}
	for _, good := range []string{BtHost + "rust/1.100.0/", BtHost + "crates/", BtHost + "dfu-util/0.11/"} {
		if err := checkBtBase(good, BtHost); err != nil {
			t.Errorf("%q: %v", good, err)
		}
	}
	m := `{"repo": "o/r", "releases": [{"tag": "t", "title": "T", "assets": [{"name": "a", "sha256": "` + strings.Repeat("a", 64) + `", "url": "https://x/a"}], "bt": {"base": "https://example.com/"}}]}`
	if _, err := Parse([]byte(m)); err == nil {
		t.Errorf("a manifest with a bt base off bt.hdlfactory.com parsed")
	}
}

// Mirror --to=bt: only releases with a bt base; built assets need
// --built_dir; every release is planned before any upload; a dry run
// uploads nothing.
func TestMirrorToBt(t *testing.T) {
	f, srv, host := btServer(t)
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("library")) }))
	defer up.Close()
	lib := Asset{Name: "lib.tar.gz", SHA256: sum("library"), URL: up.URL + "/lib.tar.gz"}
	m := &Manifest{Repo: "o/r", Releases: []Release{
		{Tag: "gh-only", Title: "G", Assets: []Asset{lib}},
		{Tag: "one", Title: "1", Assets: []Asset{lib}, Bt: &Bt{Base: host + "one/"}},
		{Tag: "two", Title: "2", Assets: []Asset{lib}, Bt: &Bt{Base: host + "two/"}},
	}}
	opts := func(dry bool, release, password string) MirrorOptions {
		return MirrorOptions{
			Options: Options{Client: srv.Client(), WorkDir: t.TempDir(), Log: &bytes.Buffer{}},
			DryRun:  dry, Release: release, To: "bt", BtPassword: password, BtHost: host,
			Run: func(argv []string) (string, error) { t.Errorf("ran %v", argv); return "", nil },
		}
	}
	if err := Mirror(m, opts(false, "", "")); err == nil || !strings.Contains(err.Error(), "BT_UPLOAD_PASSWORD") {
		t.Errorf("no password: %v", err)
	}
	if err := Mirror(m, opts(false, "gh-only", "s3cret")); err == nil || !strings.Contains(err.Error(), "no bt base") {
		t.Errorf("a release without bt: %v", err)
	}
	// Release two conflicts: nothing at all is uploaded, release one
	// neither.
	f.files["/two/lib.tar.gz"] = []byte("other")
	if err := Mirror(m, opts(false, "", "s3cret")); err == nil || !strings.Contains(err.Error(), "nothing uploaded") || f.puts != 0 {
		t.Errorf("a conflict in the second release: %v, %d PUTs", err, f.puts)
	}
	delete(f.files, "/two/lib.tar.gz")
	if err := Mirror(m, opts(true, "", "")); err != nil || f.puts != 0 {
		t.Errorf("dry run: %v, %d PUTs", err, f.puts)
	}
	if err := Mirror(m, opts(false, "", "s3cret")); err != nil {
		t.Fatal(err)
	}
	if string(f.files["/one/lib.tar.gz"]) != "library" || string(f.files["/two/lib.tar.gz"]) != "library" || f.puts != 4 {
		t.Errorf("published %d PUTs", f.puts)
	}
	built := &Manifest{Repo: "o/r", Releases: []Release{{Tag: "b", Title: "B", Bt: &Bt{Base: host + "b/"}, Assets: []Asset{
		{Name: "k", SHA256: sum("x"), Built: &Built{Source: up.URL + "/s.tar", SourceSHA256: sum("library"), Script: "make.sh"}}}}}}
	if err := Mirror(built, opts(true, "", "")); err == nil || !strings.Contains(err.Error(), "needs --built_dir") {
		t.Errorf("built asset without --built_dir: %v", err)
	}
	if err := Mirror(&Manifest{Repo: "o/r", Releases: m.Releases[:1]}, opts(true, "", "")); err == nil || !strings.Contains(err.Error(), "no release names a bt base") {
		t.Errorf("no bt release: %v", err)
	}
	o := opts(true, "", "")
	o.To = "ftp"
	if err := Mirror(m, o); err == nil {
		t.Errorf("--to=ftp accepted")
	}
}
