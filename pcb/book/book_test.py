# SPDX-License-Identifier: Apache-2.0
"""The fab chapter's figures and tables (pcb/book/BUILD.bazel):

- the placement table agrees with pcb/placement.py, the design's own
  positions, part by part, and marks only J2 as DNP;
- the fab package table lists the ZIP's files with their sizes and
  sha256s, and the ZIP itself last;
- every PNG is under 300 KB and as wide as asked, every SVG under 300 KB
  with no date left in it;
- svg_norm, the Excellon reader and the drill map's bounds check, on
  made-up input.
"""

import hashlib
import json
import os
import struct
import sys
import unittest
import zipfile

import book_png
import drill_svg
import placement
import svg_norm

MAX_BYTES = 300 * 1024

# Parts placement.py places that the assembler does not: KiCad leaves
# their footprints out of position files.
NOT_PLACED = {"JP1": "a solder jumper: copper only, no part to place"}


def path(var):
    return os.environ[var]


def read(var):
    with open(path(var), encoding="utf-8") as f:
        return f.read()


def png_width(p):
    with open(p, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError("%s is not a PNG" % p)
    return struct.unpack(">I", head[16:20])[0]


class PlacementTest(unittest.TestCase):
    def test_agrees_with_placement_py(self):
        mech = json.loads(read("MECH_JSON"))
        lines = read("PLACEMENT_TSV").splitlines()
        self.assertEqual(lines[0].split("\t"), ["designator", "value", "package", "x", "y", "rotation", "side", "dnp"])
        rows = {r[0]: r for r in (l.split("\t") for l in lines[1:])}
        for ref, (x, y, rot) in placement.positions(mech).items():
            if ref in NOT_PLACED:
                self.assertNotIn(ref, rows, "%s: %s" % (ref, NOT_PLACED[ref]))
                continue
            self.assertIn(ref, rows)
            r = rows[ref]
            self.assertAlmostEqual(float(r[3]), x, delta=0.01, msg=ref)
            self.assertAlmostEqual(float(r[4]), y, delta=0.01, msg=ref)
            self.assertAlmostEqual(float(r[5]), rot % 360, delta=0.05, msg=ref)
        self.assertEqual(sorted(k for k, r in rows.items() if r[7] == "yes"), ["J2"])


class FabPackageTest(unittest.TestCase):
    def test_lists_the_zip(self):
        lines = read("FAB_PACKAGE_TSV").splitlines()
        self.assertEqual(lines[0], "file\tsize\tsha256")
        rows = [l.split("\t") for l in lines[1:]]
        with zipfile.ZipFile(path("FAB_ZIP")) as z:
            want = [[i.filename, str(i.file_size), hashlib.sha256(z.read(i)).hexdigest()] for i in sorted(z.infolist(), key=lambda i: i.filename) if not i.is_dir()]
        self.assertEqual(rows[:-1], want)
        with open(path("FAB_ZIP"), "rb") as f:
            whole = f.read()
        self.assertEqual(rows[-1], ["(the ZIP)", str(len(whole)), hashlib.sha256(whole).hexdigest()])


class FiguresTest(unittest.TestCase):
    def test_sizes(self):
        widths = json.loads(os.environ["PNG_WIDTHS"])
        for p in os.environ["FIGURES"].split():
            size = os.path.getsize(p)
            self.assertLess(size, MAX_BYTES, "%s is %d bytes" % (p, size))
            name = os.path.basename(p)
            if p.endswith(".png"):
                w = png_width(p)
                want = widths[name]
                # KiCad's own renders come out a little smaller than asked.
                lo = want * 0.95 if name in ("top.png", "bottom.png") else want
                self.assertTrue(lo <= w <= want, "%s is %d pixels wide, want %d" % (name, w, want))
            elif p.endswith(".svg"):
                with open(p, encoding="utf-8") as f:
                    self.assertNotRegex(f.read(), r"date \d{4}/", p)


class UnitTest(unittest.TestCase):
    def test_svg_norm(self):
        text = '<svg><title>SVG Image created as x.svg date 2026/11/21 06:00:00 </title></svg>'
        self.assertEqual(svg_norm.normalize(text), "<svg><title>SVG Image created as x.svg </title></svg>")
        with self.assertRaises(ValueError):
            svg_norm.normalize("<svg><title>no date</title></svg>")

    def test_excellon(self):
        text = "M48\nMETRIC\nT1C0.300\nT2C2.700\n%\nG90\nG05\nT1\nX110.0Y-120.0\nT2\nX103.5Y-121.5\nX104.0Y-122.0G85X106.0Y-122.0\nT0\nM30\n"
        self.assertEqual(
            drill_svg.holes(text),
            [(0.3, 110.0, -120.0, 110.0, -120.0), (2.7, 103.5, -121.5, 103.5, -121.5), (2.7, 104.0, -122.0, 106.0, -122.0)],
        )
        with self.assertRaises(ValueError):
            drill_svg.holes("M48\nINCH\n%\n")

    def test_book_png_dpi(self):
        self.assertAlmostEqual(book_png.dpi_for('<svg xmlns="x" width="42.7228mm" height="26mm">', 1350), 1350 * 25.4 / 42.7228)
        with self.assertRaises(ValueError):
            book_png.dpi_for('<svg width="100" height="50">', 700)

    def test_a_hole_off_the_board(self):
        mech = json.loads(read("MECH_JSON"))
        with self.assertRaises(ValueError):
            drill_svg.svg([(0.3, 50.0, -50.0, 50.0, -50.0)], mech)


if __name__ == "__main__":
    unittest.main()
