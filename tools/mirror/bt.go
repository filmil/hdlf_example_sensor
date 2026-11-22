// SPDX-License-Identifier: Apache-2.0

package mirror

import (
	"bytes"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Bt says where on bt.hdlfactory.com a release's assets are published:
// each asset at Base + its name, with its .torrent beside it. Like
// bazel_rules_kicad's tools/models3d, the path names what is mirrored and
// its version where it has one: rust/1.100.0/, dfu-util/0.11/; crates/
// holds crates of every version, each file named with its own.
type Bt struct {
	Base string `json:"base"`
}

// BtHost is the only host a release may name.
const BtHost = "https://bt.hdlfactory.com/"

// BtUser is the upload login (serving's bt.k8s/README.md).
const BtUser = "publisher"

// PieceLength is every torrent's piece size: 1 MiB, as models3d's.
const PieceLength = 1 << 20

// CreatedBy is the torrents' "created by": the same as the .torrent of
// //third_party/dfu_util, so that a file published either way has the
// same .torrent.
const CreatedBy = "hdlf_example_sensor (as rules_kicad tools/models3d)"

// A bt path: segments of lowercase letters, digits, '.', '_' and '-',
// none of them "." or "..", each followed by '/'.
var btPath = regexp.MustCompile(`^([a-z0-9_-][a-z0-9._-]*/)+$`)

// checkBtBase checks that base is host followed by a bt path.
func checkBtBase(base, host string) error {
	rest, ok := strings.CutPrefix(base, host)
	if !ok || !btPath.MatchString(rest) || strings.Contains("/"+rest, "/../") || strings.Contains("/"+rest, "/./") {
		return fmt.Errorf("bt base %q: want %s and a path of [a-z0-9._-] segments, ending in /", base, host)
	}
	return nil
}

// torrentOf returns a single-file .torrent for the file at path, named
// name, whose only source is the web seed url (BEP 19), and the file's
// length and sha256, reading it once, a piece at a time.
func torrentOf(path, name, url string) (torrent []byte, size int64, sum string, err error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, 0, "", err
	}
	defer f.Close()
	h := sha256.New()
	var pieces []byte
	buf := make([]byte, PieceLength)
	for {
		n, err := io.ReadFull(f, buf)
		if n > 0 {
			p := sha1.Sum(buf[:n])
			pieces = append(pieces, p[:]...)
			h.Write(buf[:n])
			size += int64(n)
		}
		if err == io.EOF || err == io.ErrUnexpectedEOF {
			break
		}
		if err != nil {
			return nil, 0, "", err
		}
	}
	return torrentBytes(name, size, pieces, url), size, hex.EncodeToString(h.Sum(nil)), nil
}

// Torrent returns the .torrent of data: 1 MiB pieces, no tracker, no
// creation date, keys sorted, so the same file gives the same bytes. It
// is bazel_rules_kicad's models3d.Torrent, but for CreatedBy.
func Torrent(name string, data []byte, url string) []byte {
	var pieces []byte
	for off := 0; off < len(data); off += PieceLength {
		end := min(off+PieceLength, len(data))
		p := sha1.Sum(data[off:end])
		pieces = append(pieces, p[:]...)
	}
	return torrentBytes(name, int64(len(data)), pieces, url)
}

func torrentBytes(name string, size int64, pieces []byte, url string) []byte {
	return bencode(map[string]any{
		"created by": CreatedBy,
		"info": map[string]any{
			"length":       size,
			"name":         name,
			"piece length": int64(PieceLength),
			"pieces":       string(pieces),
		},
		"url-list": []any{url},
	})
}

// bencode encodes a string, an int64, a []any or a map[string]any (keys
// sorted, as BitTorrent requires).
func bencode(v any) []byte {
	var b bytes.Buffer
	var enc func(v any)
	enc = func(v any) {
		switch v := v.(type) {
		case string:
			fmt.Fprintf(&b, "%d:%s", len(v), v)
		case int64:
			fmt.Fprintf(&b, "i%de", v)
		case []any:
			b.WriteByte('l')
			for _, e := range v {
				enc(e)
			}
			b.WriteByte('e')
		case map[string]any:
			keys := make([]string, 0, len(v))
			for k := range v {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			b.WriteByte('d')
			for _, k := range keys {
				enc(k)
				enc(v[k])
			}
			b.WriteByte('e')
		default:
			panic(fmt.Sprintf("bencode: %T", v))
		}
	}
	enc(v)
	return b.Bytes()
}

// BtUpload is one file to publish: its URL, and either the file on disk
// (path) or its bytes (a .torrent), with its size and sha256.
type BtUpload struct {
	URL    string
	path   string
	data   []byte
	size   int64
	sha256 string
}

func (u BtUpload) body() (io.ReadCloser, error) {
	if u.path != "" {
		return os.Open(u.path)
	}
	return io.NopCloser(bytes.NewReader(u.data)), nil
}

// noRedirects keeps a client from following redirects: a PUT carries the
// password, which must go to the URL asked and nowhere else.
func noRedirects(c *http.Client) *http.Client {
	n := *c
	n.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return &n
}

// btSum fetches url without a login and returns its sha256 and size,
// read as it streams; found is false on 404. Any other status, a
// redirect included, is an error.
func btSum(client *http.Client, u string) (sum string, size int64, found bool, err error) {
	resp, err := client.Get(u)
	if err != nil {
		return "", 0, false, err
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
		h := sha256.New()
		size, err = io.Copy(h, resp.Body)
		return hex.EncodeToString(h.Sum(nil)), size, true, err
	case http.StatusNotFound:
		io.Copy(io.Discard, resp.Body) // so the connection is reused
		return "", 0, false, nil
	default:
		io.Copy(io.Discard, resp.Body)
		return "", 0, false, fmt.Errorf("GET %s: %s", u, resp.Status)
	}
}

// PlanBt returns what publishing files (paths, checked against the
// manifest) to base on host needs: each file and its .torrent that is
// not there yet. It fetches every URL without a login: a file there with
// the same bytes is left out, and one with other bytes is an error, since
// a published file never changes. Two files for one URL are an error.
func PlanBt(client *http.Client, host, base string, files []string, log io.Writer) ([]BtUpload, error) {
	if err := checkBtBase(base, host); err != nil {
		return nil, err
	}
	client = noRedirects(client)
	var all []BtUpload
	seen := map[string]bool{}
	for _, p := range files {
		name := filepath.Base(p)
		u := base + url.PathEscape(name)
		t, size, sum, err := torrentOf(p, name, u)
		if err != nil {
			return nil, err
		}
		for _, x := range []BtUpload{
			{URL: u, path: p, size: size, sha256: sum},
			{URL: u + ".torrent", data: t, size: int64(len(t)), sha256: sha(t)},
		} {
			if seen[x.URL] {
				return nil, fmt.Errorf("two files for %s", x.URL)
			}
			seen[x.URL] = true
			all = append(all, x)
		}
	}
	var missing []BtUpload
	var problems []string
	for _, x := range all {
		sum, _, found, err := btSum(client, x.URL)
		switch {
		case err != nil:
			problems = append(problems, err.Error())
		case !found:
			missing = append(missing, x)
		case sum == x.sha256:
			fmt.Fprintf(log, "ok %s: already published, the same bytes\n", x.URL)
		default:
			problems = append(problems, fmt.Sprintf("%s is published with sha256 %s, ours is %s; a published file never changes", x.URL, sum, x.sha256))
		}
	}
	if len(problems) > 0 {
		return nil, errors.New(strings.Join(problems, "\n  "))
	}
	return missing, nil
}

// UploadBt PUTs each planned file with the publisher login, streamed from
// disk, then reads it back without the login and checks its sha256.
// password goes into the requests' login only, never into a log line.
func UploadBt(client *http.Client, uploads []BtUpload, password string, log io.Writer) error {
	if password == "" {
		return fmt.Errorf("$BT_UPLOAD_PASSWORD is not set; nothing uploaded")
	}
	client = noRedirects(client)
	for _, x := range uploads {
		body, err := x.body()
		if err != nil {
			return err
		}
		req, err := http.NewRequest(http.MethodPut, x.URL, body)
		if err != nil {
			body.Close()
			return err
		}
		req.ContentLength = x.size
		req.SetBasicAuth(BtUser, password)
		resp, err := client.Do(req)
		if err != nil {
			return fmt.Errorf("PUT %s: %w", x.URL, err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
			return fmt.Errorf("PUT %s: %s", x.URL, resp.Status)
		}
		sum, size, found, err := btSum(client, x.URL)
		switch {
		case err != nil:
			return fmt.Errorf("%s after the upload: %w", x.URL, err)
		case !found:
			return fmt.Errorf("%s after the upload: 404", x.URL)
		case sum != x.sha256:
			return fmt.Errorf("%s after the upload: %d bytes with sha256 %s, uploaded %d with %s", x.URL, size, sum, x.size, x.sha256)
		}
		fmt.Fprintf(log, "published %s (%d bytes, sha256 %s)\n", x.URL, x.size, x.sha256)
	}
	return nil
}

func sha(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}
