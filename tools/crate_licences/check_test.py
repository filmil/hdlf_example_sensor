# SPDX-License-Identifier: Apache-2.0
"""Tests check.py and crate_licences.py's offline parts on made-up crates."""

import hashlib
import json
import os
import tempfile
import unittest

from tools.crate_licences import check
from tools.crate_licences import crate_licences

LOCK = '''
[[package]]
name = "fw"
version = "0.0.0"

[[package]]
name = "a"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aa"

[[package]]
name = "b-c"
version = "0.2.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bb"
'''


class Crates(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.write("a-1.0.0", [("LICENSE-MIT", b"MIT text\n"), ("LICENSE-APACHE", b"no newline at end")])
        self.write("b-c-0.2.3", [("MIT.txt", b"\xff not UTF-8\n")], reconstructed=True)
        self.readme = "| b-c 0.2.3 | MIT | SPDX |"

    def write(self, key, files, reconstructed=None):
        parts = [{"file": f, "from": "https://example.com/" + f, "bytes": b} for f, b in files]
        licence, listed = crate_licences.render(parts)
        source = {"crate": key, "files": listed}
        if reconstructed is not None:
            source["reconstructed"] = reconstructed
            source["why"] = "no upstream file"
        os.makedirs(os.path.join(self.dir, key), exist_ok=True)
        with open(os.path.join(self.dir, key, "LICENSE"), "wb") as fh:
            fh.write(licence)
        with open(os.path.join(self.dir, key, "SOURCE.json"), "w") as fh:
            json.dump(source, fh)

    def edit(self, key, name, fn):
        p = os.path.join(self.dir, key, name)
        with open(p, "rb") as fh:
            b = fh.read()
        with open(p, "wb") as fh:
            fh.write(fn(b))

    def problems(self):
        return check.check(self.dir, LOCK, self.readme)

    def test_locked_skips_path_packages(self):
        self.assertEqual(check.locked(LOCK), [("a", "1.0.0", "aa"), ("b-c", "0.2.3", "bb")])

    def test_good(self):
        self.assertEqual(self.problems(), [])

    def test_missing_directory(self):
        os.rename(os.path.join(self.dir, "a-1.0.0"), os.path.join(self.dir, "x"))
        self.assertIn("a-1.0.0: in Cargo.lock, but has no directory", self.problems())

    def test_stale_directory(self):
        self.write("a-0.9.0", [("LICENSE", b"old\n")])
        self.assertIn("a-0.9.0: has a directory, but is not in Cargo.lock", self.problems())

    def test_header_only(self):
        self.edit("a-1.0.0", "LICENSE", lambda b: b.split(b"\n")[0] + b"\n")
        self.assertTrue(any("LICENSE-MIT is not" in p for p in self.problems()), self.problems())

    def test_changed_text(self):
        self.edit("a-1.0.0", "LICENSE", lambda b: b.replace(b"MIT text", b"MIT tExt"))
        self.assertIn("a-1.0.0: LICENSE's LICENSE-MIT does not have SOURCE.json's sha256", self.problems())

    def test_trailing_bytes(self):
        self.edit("a-1.0.0", "LICENSE", lambda b: b + b"extra\n")
        self.assertIn("a-1.0.0: LICENSE has 6 bytes after its last file", self.problems())

    def test_missing_licence(self):
        os.remove(os.path.join(self.dir, "a-1.0.0", "LICENSE"))
        self.assertTrue(any(p.startswith("a-1.0.0: LICENSE:") for p in self.problems()))

    def test_malformed_source(self):
        self.edit("a-1.0.0", "SOURCE.json", lambda b: b[:-1])
        self.assertTrue(any(p.startswith("a-1.0.0: SOURCE.json:") for p in self.problems()))

    def test_wrong_crate(self):
        self.edit("a-1.0.0", "SOURCE.json", lambda b: b.replace(b'"a-1.0.0"', b'"a-2.0.0"'))
        self.assertIn("a-1.0.0: SOURCE.json names crate 'a-2.0.0'", self.problems())

    def test_reconstructed_needs_readme(self):
        self.readme = ""
        self.assertIn("b-c-0.2.3: reconstructed, but README.md does not name it", self.problems())

    def test_spdx_copyright_line(self):
        pin = {"spdx": {"commit": "c" * 40, "ids": ["MIT", "Apache-2.0"]}, "copyright": "Copyright (c) 2016 Someone"}
        texts = {"MIT": b"MIT License\n\nCopyright (c) <year> <copyright holders>\n\nPermission...\n",
                 "Apache-2.0": b"Apache License\nCopyright [yyyy] [name of copyright owner]\n"}
        real = crate_licences.get
        crate_licences.get = lambda url: texts[url.rsplit("/", 1)[1][:-4]]
        try:
            out = crate_licences.spdx_texts(pin)
        finally:
            crate_licences.get = real
        self.assertIn(b"Copyright (c) 2016 Someone", out[0][2])
        self.assertIn("reconstructed", out[0][3])
        self.assertEqual(out[1][2], texts["Apache-2.0"])

    def test_github_repo(self):
        self.assertEqual(crate_licences.github_repo("https://github.com/embassy-rs/embassy"), "embassy-rs/embassy")
        self.assertEqual(crate_licences.github_repo("https://github.com/rust-embedded/cortex-m.git"), "rust-embedded/cortex-m")
        self.assertIsNone(crate_licences.github_repo("https://gitlab.com/x/y"))


if __name__ == "__main__":
    unittest.main()
