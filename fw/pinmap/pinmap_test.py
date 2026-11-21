# SPDX-License-Identifier: Apache-2.0
"""pinmap.py on the board's own netlist, and on edits of it that must fail."""

import argparse
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

_spec = importlib.util.spec_from_file_location("pinmap", os.path.join(os.path.dirname(__file__), "pinmap.py"))
pinmap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pinmap)

ARGS = None


def read(p):
    with open(p) as f:
        return f.read()


def copy(x):
    return json.loads(json.dumps(x))


class PinmapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.netlist = read(ARGS.netlist)
        cls.symbols = read(ARGS.symbols)
        cls.meta = {m: read(m) for m in ARGS.metadata}
        cls.spec = json.loads(read(ARGS.spec))
        cls.ref = cls.spec["chip_ref"]
        cls.names = pinmap.symbol_pins(cls.symbols, cls.spec["part"]["symbol"])
        cls.number = {name: num for num, name in cls.names.items()}

    def run_on(self, netlist=None, spec=None, meta=None, symbols=None):
        """pinmap.run on the real inputs, with any of them replaced."""
        try:
            return pinmap.run(
                (ARGS.netlist, netlist or self.netlist),
                (ARGS.symbols, symbols or self.symbols),
                meta or self.meta,
                spec or self.spec,
            )
        except ValueError as e:
            return None, [str(e)]

    def problems(self, **kw):
        out, problems = self.run_on(**kw)
        self.assertIsNone(out, "a bad input gave pins.rs")
        return problems

    def move(self, net, to_pin, netlist=None):
        """The netlist with U1's node on net moved to the pin named to_pin
        (or numbered, if to_pin is digits)."""
        netlist = netlist or self.netlist
        to = to_pin if to_pin.isdigit() else self.number[to_pin]
        m = re.search(r'\(net\s*\(code "?\d+"?\)\s*\(name "%s"\).*?(?=\n    \(net|\n  \)\n)' % re.escape(net), netlist, re.S)
        self.assertIsNotNone(m, net)
        block, n = re.subn(r'(\(ref "%s"\)\s*\(pin ")\d+(")' % self.ref, r"\g<1>%s\g<2>" % to, m.group(0), count=1)
        self.assertEqual(n, 1, net)
        return netlist[: m.start()] + block + netlist[m.end():]

    # The board.

    def test_the_board_fits(self):
        out, problems = self.run_on()
        self.assertEqual(problems, [])
        self.assertIn("pub const REMAP_PA11_PA12: bool = true;", out)
        self.assertIn("pub const I2C_SDA: AfPin = AfPin { pin: Pin { port: 'F', number: 0 }, af: 1 };", out)
        self.assertIn("pub const USB_DP: Pin = Pin { port: 'A', number: 12 };", out)
        self.assertIn("#![no_std]", out)

    def test_the_pinout_table(self):
        try:
            out, problems = pinmap.run(
                (ARGS.netlist, self.netlist), (ARGS.symbols, self.symbols), self.meta, self.spec, "tsv")
        except ValueError as e:
            out, problems = None, [str(e)]
        self.assertEqual(problems, [])
        rows = [r.split("\t") for r in out.splitlines()]
        self.assertEqual(rows[0], ["pin", "name", "net", "port", "function", "af"])
        self.assertEqual([r[0] for r in rows[1:]], [str(n) for n in range(1, 21)])
        by_net = {r[2]: r for r in rows[1:]}
        self.assertEqual(by_net["I2C_SDA"][3:], ["PF0", "I2C1 SDA", "1"])
        self.assertEqual(by_net["USB_DP"][3:], ["PA12", "USB DP", ""])
        self.assertEqual(by_net["LED"][3:], ["PA4", "gpio", ""])
        self.assertEqual(by_net["BOOT0"][3:], ["PB8", "pin PB8", ""])
        for r in rows:
            self.assertEqual(len(r), 6, r)
        # A pin the firmware does not drive has no port, function or af.
        for r in rows[1:]:
            if not r[3]:
                self.assertEqual(r[4:], ["", ""], r)
        self.assertTrue(any(r[3] == "" and r[2] for r in rows[1:]), "no power or other pin")

    def test_the_pinout_table_on_made_up_pins(self):
        # KiCad's unconnected-(...) nets show as no net; pins sort by
        # number, also past 9 and with letters (BGA-style names).
        spec = {"nets": {"LED": {"gpio": True}}}
        names = {"10": "PA4", "2": "PA0", "A1": "VDD", "1": "PA9/PA11"}
        nets = {"LED": ["10"], "unconnected-(U1-PA0-Pad2)": ["2"], "+3V3": ["A1"]}
        out = pinmap.tsv(spec, nets, names, {"LED": ("PA4", None, 0, "10")})
        self.assertEqual(out.splitlines()[1:], [
            "1\tPA9/PA11\t\t\t\t",
            "2\tPA0\t\t\t\t",
            "10\tPA4\tLED\tPA4\tgpio\t",
            "A1\tVDD\t+3V3\t\t\t",
        ])

    def test_the_pinout_table_on_a_bad_board(self):
        out, problems = pinmap.run(
            (ARGS.netlist, self.move("I2C_SDA", "PA4")), (ARGS.symbols, self.symbols), self.meta, self.spec, "tsv")
        self.assertIsNone(out)
        self.assertTrue(problems)

    def test_an_unknown_format(self):
        with self.assertRaises(ValueError):
            pinmap.run((ARGS.netlist, self.netlist), (ARGS.symbols, self.symbols), self.meta, self.spec, "csv")

    # Nets on the wrong pins.

    def test_sda_on_a_pin_without_i2c(self):
        p = self.problems(netlist=self.move("I2C_SDA", "PA4"))
        self.assertIn("I2C_SDA: on U1 pin 10 (PA4), which is not I2C1 SDA", p)

    def test_scl_and_sda_swapped(self):
        p = self.problems(netlist=self.move("I2C_SCL", "PF0", self.move("I2C_SDA", "PF1")))
        self.assertEqual(sorted(x.split(":")[0] for x in p), ["I2C_SCL", "I2C_SDA"], p)

    def test_usb_dp_and_dm_swapped(self):
        # Each fails with the remap off and on: the board's problem, not the
        # remap's, reported once.
        swapped = self.move("USB_DM", "18", self.move("USB_DP", "17"))
        p = self.problems(netlist=swapped)
        self.assertEqual(p, [
            "USB_DM: on U1 pin 18 (PA10), which is not USB DM",
            "USB_DP: on U1 pin 17 (PA9), which is not USB DP",
        ])

    def test_usb_on_a_pin_without_usb(self):
        p = self.problems(netlist=self.move("USB_DP", "PA0"))
        self.assertTrue(any(x.startswith("USB_DP: on U1 pin 6 (PA0)") for x in p), p)

    def test_led_on_a_power_pin(self):
        p = self.problems(netlist=self.move("LED", "VDD"))
        self.assertIn("LED: on U1 pin 16 (VDD), which is not a port pin", p)

    def test_boot0_moved(self):
        p = self.problems(netlist=self.move("BOOT0", "PB1"))
        self.assertIn("BOOT0: on U1 pin 14 (PB1), which is not PB8", p)

    def test_two_nets_on_one_pin(self):
        p = self.problems(netlist=self.move("LED", "PA0"))
        self.assertIn("U1 pin 6 carries nets DRDY, LED, which the firmware drives apart", p)

    def test_a_split_remap(self):
        # SDA on PA10 needs the remap off; USB needs it on.
        spec = copy(self.spec)
        spec["nets"]["USB_DP"] = {"peripheral": "I2C1", "signal": "SDA"}
        p = self.problems(spec=spec)
        self.assertEqual(p[0], "no setting of the PA11/PA12 remap fits; without it:", p)
        self.assertIn("  USB_DM: on U1 pin 17 (PA9), which is not USB DM", p)
        self.assertIn("  USB_DP: on U1 pin 18 (PA12), which is not I2C1 SDA", p)

    def test_the_remap_is_one_setting(self):
        # A GPIO on pin 17 is PA11, not PA9, when USB needs the remap.
        spec = copy(self.spec)
        spec["nets"]["USB_DM"] = {"gpio": True}
        out, p = self.run_on(spec=spec)
        self.assertEqual(p, [])
        self.assertIn("USB_DM: Pin = Pin { port: 'A', number: 11 }", out)
        # With nothing that needs it, the remap stays off.
        spec["nets"]["USB_DP"] = {"gpio": True}
        out, p = self.run_on(spec=spec)
        self.assertEqual(p, [])
        self.assertIn("USB_DP: Pin = Pin { port: 'A', number: 10 }", out)
        self.assertIn("REMAP_PA11_PA12: bool = false;", out)

    # Nets missing, or not on U1.

    def test_a_missing_net(self):
        spec = copy(self.spec)
        spec["nets"]["STATUS"] = {"gpio": True}
        self.assertIn("STATUS: no such net in the netlist", self.problems(spec=spec))

    def test_a_net_on_no_pin_of_u1(self):
        m = re.search(r'\(name "LED"\)', self.netlist)
        tail = self.netlist[m.end():]
        cut = re.sub(r'\(ref "U1"\)', '(ref "U9")', tail, count=1)
        p = self.problems(netlist=self.netlist[: m.end()] + cut)
        self.assertIn("LED: on 0 pins of U1 (none), want 1", p)

    def test_a_net_on_two_pins(self):
        both = self.netlist.replace('(name "LED")', '(name "LED")\n      (node (ref "U1") (pin "11") (pintype "PASSIVE"))', 1)
        self.assertTrue(any(x.startswith("LED: on 2 pins of U1") for x in self.problems(netlist=both)))

    def test_a_pin_not_in_the_symbol(self):
        self.assertIn("LED: U1 pin 99 is not in the symbol", self.problems(netlist=self.move("LED", "99")))

    # U1 must be the part the spec names.

    def test_another_package(self):
        other = self.netlist.replace('(part "STM32F042F6Px")', '(part "STM32F042K6Tx")', 1)
        p = self.problems(netlist=other)
        self.assertIn("U1: its symbol is 'STM32F042K6Tx' in the netlist, the spec wants 'STM32F042F6Px'", p)

    def test_another_value_and_footprint(self):
        other = self.netlist.replace('(value "STM32F042F6P6")', '(value "STM32F042G6U6")', 1)
        other = other.replace('(footprint "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm")', '(footprint "Package_DFN_QFN:QFN-28")', 1)
        p = self.problems(netlist=other)
        self.assertEqual(len([x for x in p if x.startswith("U1: its value") or x.startswith("U1: its footprint")]), 2, p)

    def test_no_u1(self):
        p = self.problems(netlist=self.netlist.replace('(ref "U1")\n      (value', '(ref "U7")\n      (value', 1))
        self.assertIn("the netlist has 0 components U1, want 1", p)

    def test_another_symbol_library(self):
        self.assertTrue(any("the netlist's library is MCU_ST_STM32F0" in x for x in
                            self.problems_with_symbols_path("/x/MCU_ST_STM32F1.kicad_sym")))

    def problems_with_symbols_path(self, path):
        out, problems = pinmap.run((ARGS.netlist, self.netlist), (path, self.symbols), self.meta, self.spec)
        self.assertIsNone(out)
        return problems

    # The metadata must be the chip's, and parse in full.

    def test_metadata_of_another_chip(self):
        spec = copy(self.spec)
        spec["chip"] = "STM32F072CB"
        p = self.problems(spec=spec)
        self.assertTrue(p[0].startswith("want one chips/stm32f072cb/metadata.rs"), p)

    def test_a_shard_not_given(self):
        chip = [k for k in self.meta if k.endswith("stm32f042f6/metadata.rs")]
        p = self.problems(meta={chip[0]: self.meta[chip[0]]})
        self.assertIn("which is not among the metadata files", p[0])

    def test_metadata_naming_another_chip(self):
        meta = dict(self.meta)
        k = [k for k in meta if k.endswith("stm32f042f6/metadata.rs")][0]
        meta[k] = meta[k].replace('name: "STM32F042F6",', 'name: "STM32F042K6",')
        self.assertIn("is not the metadata of STM32F042F6", self.problems(meta=meta)[0])

    def test_metadata_this_reader_cannot_parse(self):
        meta = dict(self.meta)
        k = [k for k in meta if re.search(r"metadata_\d+\.rs$", k)][0]
        meta[k] = meta[k].replace('signal: "SDA",\n', 'signal: "SDA",\n                remap: None,\n', 1)
        self.assertIn("peripheral pins this reader does not parse", self.problems(meta=meta)[0])

    # The spec.

    def test_bad_specs(self):
        for want in ({"gpio": False}, {"pin": "NRST", "why": "x"}, {"pin": "PB8"}, {"peripheral": "I2C1"},
                     {"gpio": True, "pin": "PA0", "why": "x"}):
            spec = copy(self.spec)
            spec["nets"]["LED"] = want
            p = self.problems(spec=spec)
            self.assertTrue(p and p[0].startswith("spec: LED asks for"), (want, p))

    # The parsers.

    def test_parsers_refuse_bad_input(self):
        for bad in ("(a (b)", "(a))", '(a "b)'):
            with self.assertRaises(ValueError, msg=bad):
                pinmap.sexpr(bad)
        self.assertEqual(pinmap.sexpr(r'(a "x\"y\\z")'), [["a", 'x"y\\z']])
        with self.assertRaises(ValueError):
            pinmap.symbol_pins(self.symbols, "NoSuchChip")
        with self.assertRaises(ValueError):
            pinmap.symbol_pins('(kicad_symbol_lib (symbol "A" (extends "B")))', "A")
        with self.assertRaises(ValueError):
            pinmap.symbol_pins("", "A")
        with self.assertRaises(ValueError):
            pinmap.netlist_nets("(export (components))", "U1")
        with self.assertRaises(ValueError):
            pinmap.netlist_part("(export (nets))", "U1")

    # main(), as the genrule runs it.

    def argv(self, spec_path, out):
        a = ["--netlist", ARGS.netlist, "--symbols", ARGS.symbols, "--spec", spec_path, "--out", out]
        for m in ARGS.metadata:
            a += ["--metadata", m]
        return a

    def test_main(self):
        d = tempfile.mkdtemp(dir=os.environ.get("TEST_TMPDIR"))
        out = os.path.join(d, "pins.rs")
        self.assertEqual(pinmap.main(self.argv(ARGS.spec, out)), 0)
        self.assertEqual(read(out), self.run_on()[0])
        bad = os.path.join(d, "bad.json")
        spec = copy(self.spec)
        spec["nets"]["STATUS"] = {"gpio": True}
        with open(bad, "w") as f:
            json.dump(spec, f)
        out2 = os.path.join(d, "pins2.rs")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(pinmap.main(self.argv(bad, out2)), 1)
        self.assertIn("STATUS: no such net in the netlist", err.getvalue())
        self.assertFalse(os.path.exists(out2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--metadata", nargs="+", required=True)
    ap.add_argument("--spec", required=True)
    ARGS, rest = ap.parse_known_args()
    unittest.main(argv=[sys.argv[0]] + rest)
