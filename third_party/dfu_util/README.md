<!-- SPDX-License-Identifier: Apache-2.0 -->
# dfu-util

dfu-util 0.11, GPL-2.0-or-later (`LICENSE`, from its source distribution).
`//tools/dfu_util` builds it statically with libusb and musl, and
`//fw:flash` runs it; `fw/README.md` says more.

## Our copy of the source

The source tarball is fetched first from our copy,
`https://bt.hdlfactory.com/dfu-util/0.11/dfu-util-0.11.tar.gz`, then from
SourceForge, which refuses some clients, then from Ubuntu's snapshot
(`dfu-util_0.11.orig.tar.gz`, the same bytes). All three are pinned in
`tools/dfu_util/dfu.go` and the manifest. Next to it on bt.hdlfactory.com
is its web-seeded `.torrent`, `dfu-util-0.11.tar.gz.torrent` here,
made as bazel_rules_kicad's `tools/models3d` makes its own (below). Publishing
them is an operator step, since it needs the upload login. Publish them
before anything depends on the bt copy alone; until then the fallbacks
serve. On eph4, from a checkout of this repository, with the tarball the
build left in `/tmp/dfu-util`:

```
bash -euo pipefail <<'EOF'
F=/tmp/dfu-util/dfu-util-0.11.tar.gz
T=third_party/dfu_util/dfu-util-0.11.tar.gz.torrent
U=https://bt.hdlfactory.com/dfu-util/0.11/dfu-util-0.11.tar.gz
echo "b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e  $F" | sha256sum -c -
echo "f84502aca8273ad7b405899c7df52faaf0e285a83b43293ea1c1f4f21645de01  $T" | sha256sum -c -
# Fails here, before any upload, if kubectl cannot read the secret.
pw="$(kubectl -n bt get secret bt-upload -o jsonpath='{.data.password}' | base64 -d)"
[ -n "$pw" ]
publish() { # FILE URL SHA256: skip it if it is there with these bytes
  local got
  if got="$(curl -fsS "$2" | sha256sum | cut -c1-64)"; then
    if [ "$got" = "$3" ]; then echo "$2 is already published"; return; fi
    echo "$2 is published with other bytes ($got): a published file never changes"; return 1
  fi
  curl -fsS --netrc-file <(printf 'machine bt.hdlfactory.com login publisher password %s\n' "$pw") -T "$1" "$2"
  echo "published $2"
}
publish "$F" "$U" b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e
publish "$T" "$U.torrent" f84502aca8273ad7b405899c7df52faaf0e285a83b43293ea1c1f4f21645de01
EOF
```

The password goes from kubectl into a shell variable, and from there into
curl's netrc through a pipe, by the shell's own `printf`: it is never
printed, and in no command's arguments. A second run skips what the first
published. To check, without the login:

```
U=https://bt.hdlfactory.com/dfu-util/0.11/dfu-util-0.11.tar.gz
curl -fsS "$U" | sha256sum          # b4b53ba21a82ef7e3d4c47df2952adf5fa494f499b6b0b57c58c5d04ae8ff19e
curl -fsS "$U.torrent" | sha256sum  # f84502aca8273ad7b405899c7df52faaf0e285a83b43293ea1c1f4f21645de01
```

`tools/mirror` also publishes them, with the rest of the release
`mirror-dfu-util-0.11`, to the same place: `bazel run //tools/mirror --
--to=bt --dry_run=false --release=mirror-dfu-util-0.11
--built_dir=/tmp/dfu-util`, with `$BT_UPLOAD_PASSWORD` set (see
`tools/mirror/cmd/main.go`). Its `.torrent` is byte for byte the one here.
A file either way puts there first is skipped by the other.

## The .torrent

`dfu-util-0.11.tar.gz.torrent` is what bazel_rules_kicad's
`models3d.Torrent` makes for this file: a bencoded dictionary with
`created by`, `url-list` (the file's URL above, its only source: a web
seed, BEP 19) and `info`, which has the file's `length` (152462), `name`
(`dfu-util-0.11.tar.gz`), `piece length` 1048576, and `pieces`, the SHA-1
of each 1 MiB piece; no tracker, and no creation date. Keys are sorted, so
the same inputs give the same bytes. `//tools/dfu_util:dfu_util_test`
checks those fields and the file's sha256.
