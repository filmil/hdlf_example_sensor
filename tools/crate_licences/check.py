# SPDX-License-Identifier: Apache-2.0
"""Checks //third_party/crates/<name>-<version>/ against Cargo.lock, as
tools/crate_licences writes them: one directory per locked crate and no
other, each with a SOURCE.json that lists its files and a LICENSE that is
exactly those files, each verbatim after its header line."""

import hashlib
import json
import os
import re


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


def header(name, origin):
    return ("==> %s (%s) <==\n" % (name, origin)).encode("utf-8")


def crate_dirs(crates_dir):
    """The <name>-<version> directories under crates_dir."""
    return sorted(d for d in os.listdir(crates_dir)
                  if os.path.isdir(os.path.join(crates_dir, d)) and re.search(r"-\d+\.\d+\.\d+", d))


def check_dir(path, key):
    """Problems with one crate directory, and whether it is reconstructed."""
    problems = []
    try:
        with open(os.path.join(path, "SOURCE.json"), "rb") as fh:
            source = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        return ["%s: SOURCE.json: %s" % (key, e)], False
    try:
        with open(os.path.join(path, "LICENSE"), "rb") as fh:
            licence = fh.read()
    except OSError as e:
        return ["%s: LICENSE: %s" % (key, e)], False
    if not isinstance(source, dict) or source.get("crate") != key:
        problems.append("%s: SOURCE.json names crate %r" % (key, source.get("crate") if isinstance(source, dict) else None))
        return problems, False
    reconstructed = source.get("reconstructed", False)
    if not isinstance(reconstructed, bool):
        problems.append("%s: SOURCE.json's reconstructed is not true or false" % key)
    if reconstructed and not source.get("why"):
        problems.append("%s: reconstructed, but SOURCE.json says not why" % key)
    files = source.get("files")
    if not isinstance(files, list) or not files:
        problems.append("%s: SOURCE.json lists no file" % key)
        return problems, reconstructed is True
    at = 0
    for f in files:
        try:
            name, origin, size, digest = f["file"], f["from"], f["bytes"], f["sha256"]
        except (KeyError, TypeError):
            problems.append("%s: SOURCE.json has an entry without file, from, bytes and sha256" % key)
            return problems, reconstructed is True
        h = header(name, origin)
        if licence[at:at + len(h)] != h:
            problems.append("%s: LICENSE has no header for %s at byte %d" % (key, name, at))
            return problems, reconstructed is True
        at += len(h)
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or len(licence[at:at + size]) != size:
            problems.append("%s: LICENSE's %s is not %r bytes" % (key, name, size))
            return problems, reconstructed is True
        if hashlib.sha256(licence[at:at + size]).hexdigest() != digest:
            problems.append("%s: LICENSE's %s does not have SOURCE.json's sha256" % (key, name))
        at += size
        if licence[at:at + 1] != b"\n":
            problems.append("%s: LICENSE's %s is not followed by a newline" % (key, name))
            return problems, reconstructed is True
        at += 1
    if at != len(licence):
        problems.append("%s: LICENSE has %d bytes after its last file" % (key, len(licence) - at))
    return problems, reconstructed is True


def check(crates_dir, lock_text, readme_text):
    """All problems: missing, stale or broken directories, and reconstructed
    crates the README does not name."""
    want = {"%s-%s" % (n, v) for n, v, _ in locked(lock_text)}
    have = set(crate_dirs(crates_dir))
    problems = ["%s: in Cargo.lock, but has no directory" % k for k in sorted(want - have)]
    problems += ["%s: has a directory, but is not in Cargo.lock" % k for k in sorted(have - want)]
    for key in sorted(want & have):
        p, reconstructed = check_dir(os.path.join(crates_dir, key), key)
        problems += p
        if reconstructed:
            name, version = key.rsplit("-", 1)
            if "%s %s" % (name, version) not in readme_text:
                problems.append("%s: reconstructed, but README.md does not name it" % key)
    return problems
