# SPDX-License-Identifier: Apache-2.0
"""The fab chapter's figures and tables (pcb/book/BUILD.bazel):

- the placement table agrees with pcb/placement.py, the design's own
  positions, part by part, and marks only J2 as DNP;
- the fab package table lists the ZIP's files with their sizes and
  sha256s, and the ZIP itself last;
- every PNG is under 300 KB and as wide as asked, every SVG under 300 KB;
  each layer plot's only date is the epoch, which kicad_layers writes in
  place of the time of the plot, and drill.svg has none;
- the Excellon reader and the drill map's bounds check, on made-up input.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zipfile

import book_png
import drill_svg
import placement
import placement_tsv
import zip_tsv

MAX_BYTES = 300 * 1024

# Any date: "date " and then a digit, up to the end of the <title>.
DATE = re.compile(r"date \d[^<]*")
EPOCH = "date 1970/01/01 00:00:00 "

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
                    dates = DATE.findall(f.read())
                # kicad_layers writes the epoch into each plot's <title>;
                # drill.svg is ours and has no date.
                want = [] if name == "drill.svg" else [EPOCH]
                self.assertEqual(dates, want, p)


class UnitTest(unittest.TestCase):
    def test_excellon(self):
        text = "M48\nMETRIC\nT1C0.300\nT2C2.700\n%\nG90\nG05\nT1\nX110.0Y-120.0\nT2\nX103.5Y-121.5\nX104.0Y-122.0G85X106.0Y-122.0\nT0\nM30\n"
        self.assertEqual(
            drill_svg.holes(text),
            [(0.3, 110.0, -120.0, 110.0, -120.0), (2.7, 103.5, -121.5, 103.5, -121.5), (2.7, 104.0, -122.0, 106.0, -122.0)],
        )
        with self.assertRaises(ValueError):
            drill_svg.holes("M48\nINCH\n%\n")

    def test_book_png_dpi(self):
        dpi = book_png.dpi_for('<svg:rect width="1mm"/><svg xmlns="x" stroke-width="0.15mm" width="42.7228mm" height="26mm">', 1350)
        self.assertAlmostEqual(dpi, 1350 * 25.4 / 42.7228)
        # svgpng's width: round(mm * dpi / 25.4), with the dpi as passed.
        self.assertEqual(int(42.7228 * float("%.6f" % dpi) / 25.4 + 0.5), 1350)
        for bad, px in (('<svg width="100" height="50">', 700), ('<svg width="0mm">', 700), ('<svg width="40mm">', 0)):
            with self.assertRaises(ValueError):
                book_png.dpi_for(bad, px)

    def test_excellon_errors(self):
        head = "M48\nMETRIC\nT1C0.300\n%\n"
        for bad in (
            head + "X1.0Y1.0\n",  # no tool
            head + "T2\n",  # an undefined tool
            head + "T1\nG91\n",  # incremental coordinates
            head + "T1\nG00X1.0Y1.0\n",  # a routed slot
            head + "T1\nX1.0Y2.0\nT0\nX3.0Y4.0\n",  # a hole after T0 unloads
            head + "T1\nX0010Y0020\n",  # fixed-point coordinates
            "M48\nT1C0.300\n%\nT1\nX1.0Y1.0\n",  # no METRIC
            "M48\nT1C0.300\n%\n",  # no METRIC, empty body
            "M48\nMETRIC\nT1C0.300\nT1\nX1.0Y1.0\n",  # no %
            "M48\nMETRIC,TZ\nT1C0.300\n%\n",  # fixed-point units
            "M48\nMETRIC\nICI,ON\nT1C0.300\n%\n",  # incremental, in the header
            "M48\nMETRIC\nT0C0.300\n%\n",  # T0 defined
            "M48\nMETRIC\nT1C0.300\nT01C0.500\n%\n",  # a tool twice
            "M48\nMETRIC\nT1C0.000\n%\n",  # no diameter
        ):
            with self.assertRaises(ValueError, msg=bad):
                drill_svg.holes(bad)
        # T01 is T1; T0 unloads.
        self.assertEqual(drill_svg.holes("M48\nMETRIC\nT01C0.300\n%\nT1\nX1.0Y2.0\nT0\nM30\n"), [(0.3, 1.0, 2.0, 1.0, 2.0)])

    def test_drill_map_geometry(self):
        mech = json.loads(read("MECH_JSON"))
        width = mech["BOARD"]["width"]
        # A 0.3 mm hole at board (10, 5); a 1 mm slot from (20, 5) to (22, 5).
        y = -(100.0 + width - 5)
        text = drill_svg.svg([(0.3, 110.0, y, 110.0, y), (1.0, 120.0, y, 122.0, y)], mech)
        self.assertIn('<circle cx="10.0000" cy="%.4f" r="0.1500" fill="%s"/>' % (width - 5, drill_svg.COLOURS[0]), text)
        self.assertIn('x1="20.0000" y1="%.4f" x2="22.0000" y2="%.4f" stroke="%s" stroke-width="1.0000"' % (width - 5, width - 5, drill_svg.COLOURS[1]), text)
        too_many = [(0.1 * (i + 1), 110.0, y, 110.0, y) for i in range(len(drill_svg.COLOURS) + 1)]
        with self.assertRaises(ValueError):
            drill_svg.svg(too_many, mech)

    def test_placement_rows(self):
        def part(ref, x="120", y="-112.5", rot="0", val="v"):
            return {"Ref": ref, "Val": val, "Package": "p", "PosX": x, "PosY": y, "Rot": rot, "Side": "top"}

        rows = placement_tsv.rows([part("U1", rot="-0.01")], [part("U1", rot="-0.01"), part("J2", rot="359.98")], 40, 25)
        self.assertEqual(rows, [
            ["J2", "v", "p", "20.000", "12.500", "0.0", "top", "yes"],
            ["U1", "v", "p", "20.000", "12.500", "0.0", "top", "no"],
        ])
        for pos, pos_all in (
            ([part("U1")], [part("U1"), part("U1")]),  # twice
            ([part("U1")], [part("U1", x="121")]),  # differs
            ([part("U1")], []),  # missing from --pos_all
            ([], [part("U1", x="150")]),  # off the board
            ([], [part("U1", val="a\tb")]),  # a tab
            ([], [part("U1", rot="nan")]),  # no rotation
        ):
            with self.assertRaises(ValueError):
                placement_tsv.rows(pos, pos_all, 40, 25)

    def test_zip_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.zip")
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("b.gbr", b"bb")
                z.writestr("a.drl", b"a")
            lines = zip_tsv.table(p).splitlines()
            with open(p, "rb") as f:
                whole = f.read()
        self.assertEqual(lines, [
            "file\tsize\tsha256",
            "a.drl\t1\t" + hashlib.sha256(b"a").hexdigest(),
            "b.gbr\t2\t" + hashlib.sha256(b"bb").hexdigest(),
            "(the ZIP)\t%d\t%s" % (len(whole), hashlib.sha256(whole).hexdigest()),
        ])

    def test_drill_svg_main_reports_a_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.drl"), "w") as f:
                f.write("M48\nMETRIC\nT1C0.300\n%\nT1\nG91\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = drill_svg.main(["--drill", d, "--mech", path("MECH_JSON"), "--out", os.path.join(d, "out.svg")])
            self.assertEqual(code, 1)
            self.assertIn("drill_svg: an Excellon command this reader does not know: G91", err.getvalue())
            self.assertFalse(os.path.exists(os.path.join(d, "out.svg")))

    def test_a_hole_off_the_board(self):
        mech = json.loads(read("MECH_JSON"))
        with self.assertRaises(ValueError):
            drill_svg.svg([(0.3, 50.0, -50.0, 50.0, -50.0)], mech)


if __name__ == "__main__":
    unittest.main()
