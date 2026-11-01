# SPDX-License-Identifier: Apache-2.0
"""Unit tests of the PCB generator's helpers: sexpr, gen and spoil."""

import json
import os
import tempfile
import unittest

import zipfile

import bom
import gen
import sexpr
import spoil
import summary

MECH = {"BOARD": {"length": 40.0, "width": 25.0, "thickness": 1.6}}


class SexprTest(unittest.TestCase):
    def test_round_trip_escapes(self):
        text = '(a "tab\\there" "nl\\nx" "cr\\ry" "q\\"b\\\\s" (b 1))'
        node = sexpr.parse(text)
        self.assertEqual(node.items[1].atom, "tab\there")
        self.assertEqual(node.items[3].atom, "cr\ry")
        again = sexpr.parse(sexpr.write(node))
        self.assertEqual([i.atom for i in again.items[1:5]], [i.atom for i in node.items[1:5]])

    def test_children(self):
        node = sexpr.parse("(x (y 1) (z 2) (y 3))")
        self.assertEqual([c.arg(0) for c in node.children("y")], ["1", "3"])
        self.assertEqual(node.child("z").arg(0), "2")
        self.assertIsNone(node.child("w"))

    def test_unbalanced(self):
        with self.assertRaises(ValueError):
            sexpr.parse("(a (b)")


class RotateTest(unittest.TestCase):
    def at(self, text, rot):
        node = sexpr.parse("(pad (at %s))" % text)
        gen._rotate_at(node, rot)
        return [i.atom for i in node.child("at").items[1:]]

    def test_adds_footprint_rotation(self):
        self.assertEqual(self.at("1 2", 90), ["1", "2", "90"])
        self.assertEqual(self.at("1 2 270", 180), ["1", "2", "90"])

    def test_unlocked_without_angle(self):
        # The angle goes after x and y, before the flag.
        self.assertEqual(self.at("1 2 unlocked", 90), ["1", "2", "90", "unlocked"])

    def test_no_rotation_no_change(self):
        self.assertEqual(self.at("1 2", 0), ["1", "2"])


class GeometryTest(unittest.TestCase):
    def edges(self, *args):
        board = gen.Board(MECH, "test")
        gen.slot(board, *args)
        return board.items

    def test_vertical_slot(self):
        items = self.edges(10.0, 5.0, 10.0, 15.0, 1.0)
        self.assertEqual([i.head() for i in items], ["gr_line", "gr_line", "gr_arc", "gr_arc"])
        # Board (9.5, 5) is KiCad (109.5, 120): Y flips about the board's width.
        self.assertEqual(items[0].child("start").items[1].atom, "109.5")
        self.assertEqual(items[0].child("start").items[2].atom, "120")

    def test_horizontal_slot(self):
        items = self.edges(5.0, 10.0, 15.0, 10.0, 2.0)
        ys = {i.child("start").items[2].atom for i in items[:2]}
        self.assertEqual(ys, {"114", "116"})


class NetlistTest(unittest.TestCase):
    def test_empty_field_is_empty_string(self):
        net = """(export (version "E")
  (components (comp (ref "R1") (value "1k") (footprint "R:R") (tstamps "abc")
    (fields (field (name "LCSC") "C1") (field (name "Empty")))))
  (nets (net (code "1") (name "N") (node (ref "R1") (pin "1")))))"""
        with tempfile.NamedTemporaryFile("w", suffix=".net", delete=False) as f:
            f.write(net)
        try:
            comps, pads = gen.read_netlist(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(comps["R1"]["fields"], {"LCSC": "C1", "Empty": ""})
        self.assertEqual(pads, {("R1", "1"): "N"})


class SpoilTest(unittest.TestCase):
    def test_adds_one_track_on_the_net(self):
        board = '(kicad_pcb (net 0 "") (net 7 "SDA") (segment (net 7)))'
        out = sexpr.parse(spoil.spoil(board, "SDA", ["1", "2"], ["3", "4"]))
        segs = out.children("segment")
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[1].child("net").arg(0), "7")
        self.assertEqual(segs[1].child("layer").arg(0), "F.Cu")

    def test_unknown_net(self):
        with self.assertRaises(SystemExit):
            spoil.spoil('(kicad_pcb (net 0 ""))', "SDA", ["1", "2"], ["3", "4"])

    def test_project_ignores(self):
        pro = json.loads(spoil.project('{"board": {"design_settings": {}}}', ["tracks_crossing"]))
        self.assertEqual(pro["board"]["design_settings"]["rule_severities"], {"tracks_crossing": "ignore"})


def comp(value, fp, **fields):
    return {"value": value, "footprint": fp, "tstamp": "", "fields": fields}


class BomTest(unittest.TestCase):
    def test_groups_excludes_and_marks_dnp(self):
        comps = {
            "R10": comp("1k", "R:R", LCSC="C1"),
            "R2": comp("1k", "R:R", LCSC="C1"),
            "J2": comp("SWD", "J:J", LCSC="C9", DNP="DNP"),
            "JP1": comp("Jumper", "JP:JP", **{"Exclude from BOM": "yes"}),
        }
        rows = bom.rows(comps)
        self.assertEqual([r["Refs"] for r in rows], ["J2", "R2,R10"])
        self.assertEqual(rows[0]["DNP"], "DNP")
        self.assertEqual(rows[1]["Qty"], "2")
        self.assertTrue(bom.to_csv(rows).startswith("Refs,Value,Footprint,Qty,DNP,LCSC,MPN,Manufacturer\n"))
        md = bom.to_md(rows)
        self.assertIn("| J2 | SWD |", md)
        # DNP parts are counted apart from the parts to assemble.
        self.assertIn("2 part(s) to assemble in 1 line(s); 1 DNP part(s) in 1 line(s)", md)

    def test_flag_values(self):
        comps = {"R1": comp("1k", "R:R", LCSC="C1", DNP="0"),
                 "R2": comp("1k", "R:R", LCSC="C1", **{"Exclude from BOM": "no"})}
        rows = bom.rows(comps)
        self.assertEqual([(r["Refs"], r["DNP"]) for r in rows], [("R1,R2", "")])

    def test_mpn_splits_groups_and_odd_refs(self):
        comps = {"R1": comp("1k", "R:R", LCSC="C1", MPN="A"),
                 "R2": comp("1k", "R:R", LCSC="C1", MPN="B"),
                 "TP_GND": comp("x", "T:T", LCSC="C2")}
        refs = [r["Refs"] for r in bom.rows(comps)]
        self.assertEqual(sorted(refs), ["R1", "R2", "TP_GND"])

    def test_markdown_cells(self):
        rows = [dict.fromkeys(bom.COLUMNS, "")]
        rows[0].update({"Refs": "R1", "Value": "a|b", "Footprint": "x\ny", "Qty": "1"})
        self.assertIn("| R1 | a\\|b | x y | 1 |", bom.to_md(rows))

    def test_main_writes_both(self):
        with tempfile.TemporaryDirectory() as d:
            net = os.path.join(d, "n.net")
            with open(net, "w") as f:
                f.write('(export (components (comp (ref "R1") (value "1k") (footprint "R:R") (tstamps "a")'
                        ' (fields (field (name "LCSC") "C1")))) (nets))')
            csv_path, md_path = os.path.join(d, "b.csv"), os.path.join(d, "b.md")
            bom.main(["--netlist", net, "--csv", csv_path, "--md", md_path])
            with open(csv_path) as f:
                self.assertEqual(f.read().splitlines()[1], "R1,1k,R:R,1,,C1,,")
            with open(md_path) as f:
                self.assertTrue(f.read().startswith("# Bill of materials"))

    def test_a_placed_part_needs_lcsc(self):
        with tempfile.TemporaryDirectory() as d:
            net = os.path.join(d, "n.net")
            with open(net, "w") as f:
                f.write('(export (components (comp (ref "R1") (value "1k") (footprint "R:R") (tstamps "a")))'
                        ' (nets))')
            with self.assertRaises(SystemExit):
                bom.main(["--netlist", net, "--csv", os.path.join(d, "b.csv"), "--md", os.path.join(d, "b.md")])


MECH_SUM = {"BOARD": {"length": 40, "width": 25, "thickness": 1.6}}


def package(d, extra=()):
    z = os.path.join(d, "p.zip")
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("b-F_Cu.gtl", "xyz")
        f.writestr("b-B_Cu.gbl", "x")
        f.writestr("b_cpl.csv", "Designator,Mid X,Mid Y,Layer,Rotation\nR1,1mm,2mm,Top,0\n")
        for name in extra:
            f.writestr(name, "")
    return z


class SummaryTest(unittest.TestCase):
    def test_lists_files_and_parts(self):
        with tempfile.TemporaryDirectory() as d:
            md = summary.summary(package(d, ["sub/"]), MECH_SUM, "2L-1oz", "# Bill of materials\n\n| Refs |\n")
        self.assertIn("| Size | 40 x 25 mm |", md)
        self.assertIn("| Layers | 2 |", md)
        self.assertIn("| Copper | 1oz outer |", md)
        self.assertIn("| Assembly | top side |", md)
        self.assertIn("| b-F_Cu.gtl | 3 |", md)
        self.assertNotIn("sub/", md)
        self.assertIn("| Refs |", md)

    def test_one_line_bom(self):
        with tempfile.TemporaryDirectory() as d:
            md = summary.summary(package(d), MECH_SUM, "2L-1oz", "# Bill of materials")
        self.assertTrue(md.endswith("## Parts\n\n\n"))

    def test_stackup_must_match_the_gerbers(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                summary.summary(package(d), MECH_SUM, "4L-1oz", "")

    def test_main(self):
        with tempfile.TemporaryDirectory() as d:
            mech, bom_md, out = (os.path.join(d, n) for n in ("m.json", "b.md", "s.md"))
            with open(mech, "w") as f:
                json.dump(MECH_SUM, f)
            with open(bom_md, "w") as f:
                f.write("# Bill of materials\n\n| Refs |\n")
            summary.main(["--zip", package(d), "--mech", mech, "--stackup", "2L-1oz", "--bom", bom_md, "--out", out])
            with open(out) as f:
                self.assertIn("# JLCPCB package of the sensor board", f.read())


class MainTest(unittest.TestCase):
    def test_pro_must_be_kicad_pro(self):
        with self.assertRaises(SystemExit):
            gen.main(["--mech", "m", "--netlist", "n", "--footprints", "f", "--pcb", "p", "--pro", "x.json"])


if __name__ == "__main__":
    unittest.main()
