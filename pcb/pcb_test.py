# SPDX-License-Identifier: Apache-2.0
"""Unit tests of the PCB generator's helpers: sexpr, gen and spoil."""

import json
import os
import tempfile
import unittest

import gen
import sexpr
import spoil

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


class MainTest(unittest.TestCase):
    def test_pro_must_be_kicad_pro(self):
        with self.assertRaises(SystemExit):
            gen.main(["--mech", "m", "--netlist", "n", "--footprints", "f", "--pcb", "p", "--pro", "x.json"])


if __name__ == "__main__":
    unittest.main()
