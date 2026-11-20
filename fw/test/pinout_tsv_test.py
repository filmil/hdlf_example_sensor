# SPDX-License-Identifier: Apache-2.0
"""//fw:pinout_tsv agrees with //fw:pins_rs: every pin const of pins.rs is
a row of the table with the same net, port and alternate function, and
no other row names a port."""

import os
import re
import unittest


def read(var):
    with open(os.environ[var]) as f:
        return f.read()


class PinoutTsvTest(unittest.TestCase):
    def test_agrees_with_pins_rs(self):
        consts = {}
        for m in re.finditer(
            r"pub const (\w+): (?:AfPin = AfPin \{ pin: )?(?:Pin = )?Pin \{ port: '([A-F])', number: (\d+) \}(?:, af: (\d+) \})?;",
            read("PINS_RS"),
        ):
            consts[m.group(1)] = ("P%s%s" % (m.group(2), m.group(3)), m.group(4) or "")
        self.assertTrue(consts, "no pin in pins.rs")
        rows = [r.split("\t") for r in read("PINOUT_TSV").splitlines()[1:]]
        ported = {r[2]: (r[3], r[5]) for r in rows if r[3]}
        self.assertEqual(ported, consts)


if __name__ == "__main__":
    unittest.main()
