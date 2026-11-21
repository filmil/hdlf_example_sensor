# SPDX-License-Identifier: Apache-2.0
"""placement_tsv --pos CSV --pos_all CSV --mech JSON --out TSV: where the
assembler puts each part, for the book's fab chapter to draw.

--pos is the CPL file JLCPCB gets (//pcb:pos, DNP parts left out);
--pos_all is the same with every part. Each row: designator, value,
package, x and y in the board's frame (mm, lower-left corner at the
origin, Y up, as mech/mechanics.bzl), rotation (degrees, 0 to 359.9),
side (top or bottom), and dnp (yes for a part in --pos_all only).
kicad_pos measures from KiCad's page with Y up; pcb/gen.py puts the
board's lower-left corner at (ORIGIN_X, ORIGIN_Y + width) on the page.
"""

import argparse
import csv
import json
import sys

import gen

HEADER = ["designator", "value", "package", "x", "y", "rotation", "side", "dnp"]


def rows(pos, pos_all, length, width):
    """The table's rows. Fails on a designator twice, a part of --pos
    that --pos_all lacks or has elsewhere, a part off the board, or a
    field with a tab or a newline."""
    for name, table in (("--pos", pos), ("--pos_all", pos_all)):
        refs = [r["Ref"] for r in table]
        twice = sorted({x for x in refs if refs.count(x) > 1})
        if twice:
            raise ValueError("%s lists %s twice" % (name, ", ".join(twice)))
    by_ref = {r["Ref"]: r for r in pos_all}
    for r in pos:
        if r["Ref"] in by_ref and by_ref[r["Ref"]] != r:
            raise ValueError("%s differs between --pos and --pos_all" % r["Ref"])
    placed = {r["Ref"] for r in pos}
    out = []
    for r in sorted(pos_all, key=lambda r: r["Ref"]):
        for k in ("Ref", "Val", "Package", "Side"):
            if any(c in r[k] for c in "\t\r\n"):
                raise ValueError("%s: its %s has a tab or a newline" % (r["Ref"], k))
        # Page X; page Y grows down, the CSV's Y up: page y = -PosY.
        x = float(r["PosX"]) - gen.ORIGIN_X
        y = gen.ORIGIN_Y + width + float(r["PosY"])
        if not (0 <= x <= length and 0 <= y <= width):
            raise ValueError("%s at (%.3f, %.3f) in the board's frame, outside the board" % (r["Ref"], x, y))
        # Rounded first, so that -0.01 is 0.0, not 360.0.
        rot = round(float(r["Rot"]), 1) % 360
        out.append([r["Ref"], r["Val"], r["Package"], "%.3f" % x, "%.3f" % y, "%.1f" % rot, r["Side"], "no" if r["Ref"] in placed else "yes"])
    extra = placed - {r["Ref"] for r in pos_all}
    if extra:
        raise ValueError("in --pos but not --pos_all: %s" % ", ".join(sorted(extra)))
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pos", required=True)
    ap.add_argument("--pos_all", required=True)
    ap.add_argument("--mech", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    def read(p):
        with open(p, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    with open(a.mech, encoding="utf-8") as f:
        board = json.load(f)["BOARD"]
    try:
        table = rows(read(a.pos), read(a.pos_all), board["length"], board["width"])
    except (ValueError, KeyError) as e:
        sys.stderr.write("placement_tsv: %s\n" % e)
        return 1
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in table:
            f.write("\t".join(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
