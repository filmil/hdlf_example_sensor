# SPDX-License-Identifier: Apache-2.0
"""//fw:pinout_tsv agrees with //fw:pins_rs: every pin const of pins.rs is
a row of the table with the same net, port and alternate function; each
net is on one row; and a row with no port has no function or af."""

import os
import re
import unittest

HEADER = ["pin", "name", "net", "port", "function", "af"]
CONST = re.compile(
    r"pub const (\w+): (?:AfPin = AfPin \{ pin: Pin \{ port: '([A-Z])', number: (\d+) \}, af: (\d+) \}"
    r"|Pin = Pin \{ port: '([A-Z])', number: (\d+) \});"
)


def read(var):
    with open(os.environ[var]) as f:
        return f.read()


class PinoutTsvTest(unittest.TestCase):
    def test_agrees_with_pins_rs(self):
        rs = read("PINS_RS")
        consts = {}
        for m in CONST.finditer(rs):
            if m.group(2):
                consts[m.group(1)] = ("P%s%s" % (m.group(2), m.group(3)), m.group(4))
            else:
                consts[m.group(1)] = ("P%s%s" % (m.group(5), m.group(6)), "")
        pin_consts = [n for n in re.findall(r"pub const (\w+): (?:Pin|AfPin) =", rs)]
        self.assertEqual(sorted(consts), sorted(pin_consts), "a pin const of pins.rs this test cannot read")
        self.assertTrue(consts, "no pin in pins.rs")

        lines = read("PINOUT_TSV").splitlines()
        self.assertEqual(lines[0].split("\t"), HEADER)
        rows = [r.split("\t") for r in lines[1:]]
        ported = {}
        for r in rows:
            self.assertEqual(len(r), len(HEADER), r)
            if not r[3]:
                self.assertEqual(r[4:], ["", ""], "a row with no port but a function or af: %s" % r)
                continue
            self.assertTrue(r[4], "a row with a port but no function: %s" % r)
            self.assertNotIn(r[2], ported, "net %s on two rows" % r[2])
            ported[r[2]] = (r[3], r[5])
        self.assertEqual(ported, consts)


if __name__ == "__main__":
    unittest.main()
