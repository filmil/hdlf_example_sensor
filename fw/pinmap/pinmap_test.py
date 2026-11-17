# SPDX-License-Identifier: Apache-2.0
"""pinmap.py on the board's own netlist, and on edits of it that must fail."""

import argparse
import importlib.util
import json
import os
import re
import sys
import unittest

_spec = importlib.util.spec_from_file_location("pinmap", os.path.join(os.path.dirname(__file__), "pinmap.py"))
pinmap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pinmap)

ARGS = None


def read(p):
    with open(p) as f:
        return f.read()


class PinmapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.netlist = read(ARGS.netlist)
        cls.names = pinmap.symbol_pins(read(ARGS.symbols), "STM32F042F6Px")
        cls.ports, cls.signals = pinmap.metadata([read(m) for m in ARGS.metadata.split()])
        cls.spec = json.loads(read(ARGS.spec))
        cls.number = {name: num for num, name in cls.names.items()}

    def run_on(self, netlist, spec=None):
        nets = pinmap.netlist_nets(netlist, "U1")
        return pinmap.resolve(spec or self.spec, nets, self.names, self.ports, self.signals)

    def move(self, net, to_pin_name):
        """The netlist with U1's node on net moved to the pin named to_pin_name."""
        to = self.number[to_pin_name]
        m = re.search(r'\(net\s*\(code "?\d+"?\)\s*\(name "%s"\).*?(?=\n    \(net|\n  \)\n)' % re.escape(net), self.netlist, re.S)
        self.assertIsNotNone(m, net)
        block = re.sub(r'(\(ref "U1"\)\s*\(pin ")\d+(")', r"\g<1>%s\g<2>" % to, m.group(0), count=1)
        return self.netlist[: m.start()] + block + self.netlist[m.end():]

    def test_the_board_fits(self):
        chosen, problems = self.run_on(self.netlist)
        self.assertEqual(problems, [])
        self.assertEqual(chosen["I2C_SDA"], ("PF0", 1, 0))
        self.assertEqual(chosen["USB_DP"], ("PA12", None, 1))
        out = pinmap.rust(chosen)
        self.assertIn("pub const REMAP_PA11_PA12: bool = true;", out)
        self.assertIn("#![no_std]", out)

    def test_sda_on_a_pin_without_i2c(self):
        _, problems = self.run_on(self.move("I2C_SDA", "PA4"))
        self.assertTrue(any(p.startswith("I2C_SDA:") and "not I2C1 SDA" in p for p in problems), problems)

    def test_scl_and_sda_swapped(self):
        swapped = self.move("I2C_SDA", "PF1")
        swapped = self.move_in(swapped, "I2C_SCL", "PF0")
        _, problems = self.run_on(swapped)
        self.assertEqual(len([p for p in problems if p.startswith("I2C_")]), 2, problems)

    def move_in(self, netlist, net, to_pin_name):
        saved, self.netlist = self.netlist, netlist
        try:
            return self.move(net, to_pin_name)
        finally:
            self.netlist = saved

    def test_usb_on_a_pin_without_usb(self):
        _, problems = self.run_on(self.move("USB_DP", "PA0"))
        self.assertTrue(any(p.strip().startswith("USB_DP:") for p in problems), problems)

    def test_led_on_a_power_pin(self):
        _, problems = self.run_on(self.move("LED", "VDD"))
        self.assertTrue(any(p.startswith("LED:") and "not a port pin" in p for p in problems), problems)

    def test_boot0_moved(self):
        _, problems = self.run_on(self.move("BOOT0", "PB1"))
        self.assertTrue(any(p.startswith("BOOT0:") and "not PB8" in p for p in problems), problems)

    def test_a_missing_net(self):
        spec = dict(self.spec, nets=dict(self.spec["nets"], STATUS={"gpio": True}))
        _, problems = self.run_on(self.netlist, spec)
        self.assertIn("STATUS: no such net in the netlist", problems)

    def test_a_net_on_two_pins(self):
        both = self.netlist.replace('(name "LED")', '(name "LED")\n      (node (ref "U1") (pin "11") (pintype "PASSIVE"))', 1)
        _, problems = self.run_on(both)
        self.assertTrue(any(p.startswith("LED:") and "on 2 pins" in p for p in problems), problems)

    def test_a_split_remap(self):
        # SDA on PA10, which needs the remap off, while USB needs it on.
        spec = json.loads(json.dumps(self.spec))
        spec["nets"]["USB_DP"] = {"peripheral": "I2C1", "signal": "SDA"}
        _, problems = self.run_on(self.netlist, spec)
        self.assertEqual(problems[0], "no setting of the PA11/PA12 remap fits; without it:", problems)
        self.assertIn("  USB_DM: on U1 pin 17 (PA9), which is not USB DM", problems)
        self.assertIn("  USB_DP: on U1 pin 18 (PA12), which is not I2C1 SDA", problems)

    def test_the_remap_is_chosen_for_the_whole_chip(self):
        # A GPIO on pin 17 takes PA11, not PA9, when USB needs the remap.
        spec = json.loads(json.dumps(self.spec))
        spec["nets"]["USB_DM"] = {"gpio": True}
        chosen, problems = self.run_on(self.netlist, spec)
        self.assertEqual(problems, [])
        self.assertEqual(chosen["USB_DM"], ("PA11", None, 1))
        # With nothing that needs it, the remap stays off.
        spec["nets"]["USB_DP"] = {"gpio": True}
        chosen, problems = self.run_on(self.netlist, spec)
        self.assertEqual((problems, chosen["USB_DM"][0], chosen["USB_DP"][0]), ([], "PA9", "PA10"))
        self.assertIn("REMAP_PA11_PA12: bool = false;", pinmap.rust(chosen))

    def test_parsers_refuse_bad_input(self):
        with self.assertRaises(ValueError):
            pinmap.sexpr("(a (b)")
        with self.assertRaises(ValueError):
            pinmap.symbol_pins(read(ARGS.symbols), "NoSuchChip")
        with self.assertRaises(ValueError):
            pinmap.metadata(["nothing here"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for f in ("--netlist", "--symbols", "--metadata", "--spec"):
        ap.add_argument(f, required=True)
    ARGS, rest = ap.parse_known_args()
    unittest.main(argv=[sys.argv[0]] + rest)
