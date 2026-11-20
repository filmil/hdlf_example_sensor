# SPDX-License-Identifier: Apache-2.0
"""Writes //third_party/crates/<name>-<version>/ for every registry crate of
third_party/crates/Cargo.lock: LICENSE, the crate's licence files verbatim,
and SOURCE.json, where each came from and its sha256.

    bazel run //tools/crate_licences

Run it by hand, after Cargo.lock changes; it fetches from the network, so no
build or test runs it. //fw:licence_test checks what it wrote.

A crate's licence files come from its .crate, checked against Cargo.lock's
checksum, when it ships any. Many workspace crates (cortex-m, embassy) do
not: their licence is at the repository's root. For those, the files come
from the repository at the commit the crate recorded (.cargo_vcs_info.json)
and the repository its Cargo.toml names, looking in the crate's directory
and then each directory above it, up to the root. A crate that records
neither, or whose repository has no licence file, is pinned by hand in
pins.json, by full commit SHA: to its repository at a chosen commit, or,
when no licence file exists upstream at all, to SPDX's standard texts,
with MIT's copyright line filled from the pin. Those carry
"reconstructed": true in SOURCE.json.
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request

UA = {"User-Agent": "hdlf-example-sensor-crate-licences"}
NAMES = ["LICENSE", "LICENSE-APACHE", "LICENSE-MIT", "LICENSE.md", "LICENSE.txt", "LICENSE-APACHE.md",
         "LICENSE-MIT.md", "LICENCE", "COPYING", "UNLICENSE", "COPYRIGHT", "NOTICE"]
LICENCE_FILE = re.compile(r"^(licen[cs]e|copying|unlicense|copyright|notice)", re.I)


def locked(lock_text):
    """[(name, version, checksum)] of a Cargo.lock's registry packages."""
    out = []
    for block in lock_text.split("[[package]]")[1:]:
        def field(k):
            m = re.search(r'(?m)^' + k + r' = "([^"]+)"', block)
            return m.group(1) if m else None
        if field("source"):
            out.append((field("name"), field("version"), field("checksum")))
    return out


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def crate_files(data):
    """The .crate's top-level licence files, {name: bytes}, and its
    .cargo_vcs_info.json and Cargo.toml [package]."""
    files, vcs, pkg = {}, None, {}
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            parts = m.name.split("/", 1)
            if not m.isfile() or len(parts) != 2:
                continue
            rel = parts[1]
            if "/" not in rel and LICENCE_FILE.match(rel):
                files[rel] = t.extractfile(m).read()
            elif rel == ".cargo_vcs_info.json":
                vcs = json.load(t.extractfile(m))
            elif rel == "Cargo.toml":
                pkg = tomllib.load(t.extractfile(m)).get("package", {})
    return files, vcs, pkg


def github_repo(url):
    m = re.match(r"https://github\.com/([^/]+/[^/.]+)", url or "")
    return m.group(1) if m else None


def upstream(repo, commit, path):
    """The licence files in repo at commit: in path, else the nearest
    directory above it that has any. ({name: (url, bytes)}, dir)."""
    dirs = []
    p = path.strip("/")
    while True:
        dirs.append(p)
        if not p:
            break
        p = p.rsplit("/", 1)[0] if "/" in p else ""
    for d in dirs:
        found = {}
        for name in NAMES:
            url = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, commit, (d + "/" if d else "") + name)
            try:
                found[name] = (url, get(url))
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
        if found:
            return found, d
    return {}, None


SPDX_PLACEHOLDER = "Copyright (c) <year> <copyright holders>"


def spdx_texts(pin):
    """SPDX's standard texts for a pin, MIT's copyright line filled in.
    [(file, from, bytes, note)]."""
    out = []
    for lid in pin["spdx"]["ids"]:
        url = "https://raw.githubusercontent.com/spdx/license-list-data/%s/text/%s.txt" % (pin["spdx"]["commit"], lid)
        text = get(url).decode("utf-8")
        note = "SPDX's standard text; no upstream licence file exists"
        if SPDX_PLACEHOLDER in text:
            text = text.replace(SPDX_PLACEHOLDER, pin["copyright"])
            note += "; the copyright line is reconstructed from Cargo.toml's authors and the publish year"
        elif lid == "MIT":
            raise ValueError("SPDX's MIT text has no placeholder line at %s" % pin["spdx"]["commit"])
        out.append((lid + ".txt", url, text.encode("utf-8"), note))
    return out


def render(parts):
    """LICENSE: each file verbatim, after a line naming it and its origin."""
    out = []
    for p in parts:
        out.append("==> %s (%s) <==\n" % (p["file"], p["from"]))
        text = p["bytes"].decode("utf-8", "replace")
        out.append(text if text.endswith("\n") else text + "\n")
        out.append("\n")
    return "".join(out)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    a = ap.parse_args(argv)
    lock = open(os.path.join(a.root, "third_party/crates/Cargo.lock")).read()
    pins = json.load(open(os.path.join(a.root, "tools/crate_licences/pins.json")))["crates"]
    problems = []
    for name, version, checksum in locked(lock):
        key = "%s-%s" % (name, version)
        data = get("https://static.crates.io/crates/%s/%s/download" % (name, version))
        if sha256(data) != checksum:
            problems.append("%s: the .crate's sha256 is not Cargo.lock's" % key)
            continue
        files, vcs, pkg = crate_files(data)
        parts = []
        if files:
            for f in sorted(files):
                parts.append({"file": f, "from": "the .crate", "bytes": files[f]})
        elif key in pins and "spdx" in pins[key]:
            for f, url, b, note in spdx_texts(pins[key]):
                parts.append({"file": f, "from": url, "bytes": b, "note": note})
        else:
            pin = pins.get(key)
            if pin:
                repo, commit, path = pin["repo"], pin["commit"], pin["path"]
            else:
                repo = github_repo(pkg.get("repository"))
                commit = (vcs or {}).get("git", {}).get("sha1")
                path = (vcs or {}).get("path_in_vcs", "")
            if not repo or not commit or not re.match(r"^[0-9a-f]{40}$", commit):
                problems.append("%s: ships no licence and records no repository and commit; pin it in pins.json" % key)
                continue
            found, d = upstream(repo, commit, path)
            if not found:
                problems.append("%s: no licence file in %s at %s" % (key, repo, commit))
                continue
            for f in sorted(found):
                parts.append({"file": f, "from": found[f][0], "bytes": found[f][1]})
        out = os.path.join(a.root, "third_party/crates", key)
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "LICENSE"), "w") as fh:
            fh.write(render(parts))
        with open(os.path.join(out, "SOURCE.json"), "w") as fh:
            source = {"crate": key}
            if key in pins:
                source["reconstructed"] = bool(pins[key].get("reconstructed"))
                source["why"] = pins[key]["why"]
            source["files"] = []
            for p in parts:
                f = {"file": p["file"], "from": p["from"], "sha256": sha256(p["bytes"])}
                if "note" in p:
                    f["note"] = p["note"]
                source["files"].append(f)
            json.dump(source, fh, indent=2)
            fh.write("\n")
        print("%s: %s" % (key, ", ".join("%s from %s" % (p["file"], "the .crate" if p["from"] == "the .crate" else "upstream") for p in parts)))
    if problems:
        sys.stderr.write("crate_licences:\n  " + "\n  ".join(problems) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
