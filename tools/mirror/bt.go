// SPDX-License-Identifier: Apache-2.0

package mirror

import (
	"bytes"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Bt says where on bt.hdlfactory.com a release's assets are published:
// each asset at Base + its name, with its .torrent beside it. The layout
// is bazel_rules_kicad's tools/models3d's: <project>/<component>/<version>/.
type Bt struct {
	Base string `json:"base"`
}

// BtHost is the only host a release may name.
const BtHost = "https://bt.hdlfactory.com/"

// btHost is BtHost, but for tests, which point it at a local server.
var btHost = BtHost

// BtUser is the upload login (serving's bt.k8s/README.md).
const BtUser = "publisher"

// PieceLength is every torrent's piece size: 1 MiB, as models3d's.
const PieceLength = 1 << 20

// CreatedBy is the torrents' "created by": the same as the .torrent of
// //third_party/dfu_util, so that a file published either way has the
// same .torrent.
const CreatedBy = "hdlf_example_sensor (as rules_kicad tools/models3d)"

func checkBtBase(base string) error {
	u, err := url.Parse(base)
	if err != nil || !strings.HasPrefix(base, btHost) || !strings.HasSuffix(base, "/") || len(base) == len(btHost) ||
		u.RawQuery != "" || u.Fragment != "" || strings.Contains(u.Path, "/../") || strings.Contains(u.Path, "/./") || strings.Contains(u.Path, "//") {
		return fmt.Errorf("bt base %q: want %s<path>/", base, btHost)
	}
	return nil
}

// Torrent returns a single-file .torrent for data, named name, whose only
// source is the web seed url (BEP 19): 1 MiB pieces, no tracker, no
// creation date, keys sorted, so the same file gives the same bytes. It
// is bazel_rules_kicad's models3d.Torrent, but for CreatedBy.
func Torrent(name string, data []byte, url string) []byte {
	var pieces []byte
	for off := 0; off < len(data); off += PieceLength {
		end := off + PieceLength
		if end > len(data) {
			end = len(data)
		}
		sum := sha1.Sum(data[off:end])
		pieces = append(pieces, sum[:]...)
	}
	return bencode(map[string]any{
		"created by": CreatedBy,
		"info": map[string]any{
			"length":       int64(len(data)),
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

// btFile is one file to publish: its URL and bytes.
type btFile struct {
	url  string
	data []byte
}

// btGet fetches url without a login: its bytes, or ok false on 404.
func btGet(client *http.Client, u string) (data []byte, ok bool, err error) {
	resp, err := client.Get(u)
	if err != nil {
		return nil, false, err
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
		data, err = io.ReadAll(resp.Body)
		return data, true, err
	case http.StatusNotFound:
		return nil, false, nil
	default:
		return nil, false, fmt.Errorf("GET %s: %s", u, resp.Status)
	}
}

func sha(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

// PublishBt publishes files (paths, checked against the manifest) to
// base on bt.hdlfactory.com, each with its .torrent. It first fetches
// every URL without a login: a file there with the same bytes is skipped,
// and one with other bytes stops it before anything is uploaded, since a
// published file never changes. Then, unless dryRun, it PUTs each
// missing file with the publisher login and reads it back. password is
// used only for the PUTs; it is never printed.
func PublishBt(client *http.Client, base string, files []string, password string, dryRun bool, log io.Writer) error {
	if err := checkBtBase(base); err != nil {
		return err
	}
	var all []btFile
	for _, p := range files {
		data, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		name := filepath.Base(p)
		u := base + url.PathEscape(name)
		all = append(all, btFile{u, data}, btFile{u + ".torrent", Torrent(name, data, u)})
	}
	var missing []btFile
	var problems []string
	for _, f := range all {
		got, ok, err := btGet(client, f.url)
		switch {
		case err != nil:
			problems = append(problems, err.Error())
		case !ok:
			missing = append(missing, f)
		case sha(got) == sha(f.data):
			fmt.Fprintf(log, "ok %s: already published, the same bytes\n", f.url)
		default:
			problems = append(problems, fmt.Sprintf("%s is published with sha256 %s, ours is %s; a published file never changes", f.url, sha(got), sha(f.data)))
		}
	}
	if len(problems) > 0 {
		return fmt.Errorf("nothing uploaded to bt:\n  %s", strings.Join(problems, "\n  "))
	}
	for _, f := range missing {
		if dryRun {
			fmt.Fprintf(log, "would PUT %s (%d bytes, sha256 %s)\n", f.url, len(f.data), sha(f.data))
			continue
		}
		if password == "" {
			return fmt.Errorf("$BT_UPLOAD_PASSWORD is not set; nothing uploaded")
		}
		req, err := http.NewRequest(http.MethodPut, f.url, bytes.NewReader(f.data))
		if err != nil {
			return err
		}
		req.ContentLength = int64(len(f.data))
		req.SetBasicAuth(BtUser, password)
		resp, err := client.Do(req)
		if err != nil {
			return fmt.Errorf("PUT %s: %w", f.url, err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
			return fmt.Errorf("PUT %s: %s", f.url, resp.Status)
		}
		got, ok, err := btGet(client, f.url)
		if err != nil || !ok || sha(got) != sha(f.data) {
			return fmt.Errorf("%s after the upload: not the bytes uploaded (%v)", f.url, err)
		}
		fmt.Fprintf(log, "published %s (%d bytes, sha256 %s)\n", f.url, len(f.data), sha(f.data))
	}
	return nil
}
