# SPDX-License-Identifier: Apache-2.0
"""Checks that the USB data pair is matched and stays on one layer.

    pair_test.py BOARD.kicad_pcb

D+ runs USB_DP_C (receptacle to the ESD protector) then USB_DP (on to the
microcontroller), and D- likewise. The two lines' track lengths may
differ by at most MAX_MISMATCH_MM, and neither may change layer (no via).

Full Speed USB (12 Mb/s, 83 ns bits, 4 to 20 ns edges) would take far more
skew; 1 mm (about 7 ps on FR-4) keeps the pair matched as a pair, so that
a change of placement that pulls them apart fails here, not on a bench.
"""

import math
import sys
import unittest

import sexpr

MAX_MISMATCH_MM = 1.0
LINES = {"D+": ["USB_DP_C", "USB_DP"], "D-": ["USB_DM_C", "USB_DM"]}

BOARD = None


def measure(text):
    """Per net: the track length (mm), the layers, and the number of vias."""
    root = sexpr.parse(text)
    names = {n.arg(0): n.arg(1) for n in root.children("net")}
    out = {}
    for seg in root.children("segment"):
        net = names[seg.child("net").arg(0)]
        s, e = seg.child("start"), seg.child("end")
        length = math.hypot(float(e.arg(0)) - float(s.arg(0)), float(e.arg(1)) - float(s.arg(1)))
        m = out.setdefault(net, {"length": 0.0, "layers": set(), "vias": 0})
        m["length"] += length
        m["layers"].add(seg.child("layer").arg(0))
    for via in root.children("via"):
        net = names[via.child("net").arg(0)]
        out.setdefault(net, {"length": 0.0, "layers": set(), "vias": 0})["vias"] += 1
    return out


class PairTest(unittest.TestCase):
    def setUp(self):
        with open(BOARD, encoding="utf-8") as f:
            self.nets = measure(f.read())

    def length(self, line):
        return sum(self.nets[n]["length"] for n in LINES[line])

    def test_matched(self):
        dp, dm = self.length("D+"), self.length("D-")
        print("D+ %.2f mm, D- %.2f mm, mismatch %.2f mm" % (dp, dm, abs(dp - dm)))
        self.assertLessEqual(abs(dp - dm), MAX_MISMATCH_MM)

    def test_one_layer_no_vias(self):
        layers = set()
        for nets in LINES.values():
            for n in nets:
                self.assertEqual(self.nets[n]["vias"], 0, "%s has a via" % n)
                layers |= self.nets[n]["layers"]
        self.assertEqual(len(layers), 1, "the pair is on %s" % sorted(layers))


class MeasureTest(unittest.TestCase):
    def test_measure(self):
        text = '''(kicad_pcb (net 0 "") (net 1 "A")
            (segment (start 0 0) (end 3 4) (width 0.2) (layer "F.Cu") (net 1))
            (via (at 3 4) (net 1)))'''
        m = measure(text)["A"]
        self.assertAlmostEqual(m["length"], 5.0)
        self.assertEqual(m["vias"], 1)
        self.assertEqual(m["layers"], {"F.Cu"})


if __name__ == "__main__":
    BOARD = sys.argv.pop(1)
    unittest.main()
