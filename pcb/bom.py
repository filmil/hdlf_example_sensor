# SPDX-License-Identifier: Apache-2.0
"""The board's bill of materials, from the circuit's netlist.

    bom.py --netlist N.net --csv BOM.csv --md BOM.md

The board has no schematic for kicad_bom to read, so this reads the
netlist instead and writes what fab_package takes: a CSV with the columns
Refs, Value, Footprint, Qty, DNP, LCSC, MPN and Manufacturer, one row per
group of alike parts. A part with the field "Exclude from BOM" (the solder
jumper) is left out; one with "DNP" keeps its row, marked, and
fab_package leaves it out of the vendor's BOM.

BOM.md is the same, as a Markdown table, for people.
"""

import argparse
import csv
import io
import re
import sys

import gen

COLUMNS = ["Refs", "Value", "Footprint", "Qty", "DNP", "LCSC", "MPN", "Manufacturer"]


def _ref_key(ref):
    m = re.match(r"([A-Za-z]+)(\d+)$", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def rows(comps):
    groups = {}
    for ref, c in comps.items():
        f = c["fields"]
        if "Exclude from BOM" in f:
            continue
        key = (c["value"], c["footprint"], f.get("LCSC", ""), f.get("MPN", ""),
               f.get("Manufacturer", ""), "DNP" if "DNP" in f else "")
        groups.setdefault(key, []).append(ref)
    out = []
    for (value, fp, lcsc, mpn, mfr, dnp), refs in groups.items():
        refs = sorted(refs, key=_ref_key)
        out.append({"Refs": ",".join(refs), "Value": value, "Footprint": fp, "Qty": str(len(refs)),
                    "DNP": dnp, "LCSC": lcsc, "MPN": mpn, "Manufacturer": mfr})
    return sorted(out, key=lambda r: _ref_key(r["Refs"].split(",")[0]))


def to_csv(rs):
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rs)
    return b.getvalue()


def to_md(rs):
    lines = ["# Bill of materials", "",
             "%d part(s) in %d line(s); DNP parts are not assembled." % (
                 sum(int(r["Qty"]) for r in rs), len(rs)), "",
             "| " + " | ".join(COLUMNS) + " |", "|" + "|".join(["---"] * len(COLUMNS)) + "|"]
    for r in rs:
        lines.append("| " + " | ".join(r[c].replace("|", "\\|") for c in COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def main(argv):
    p = argparse.ArgumentParser(prog="bom")
    p.add_argument("--netlist", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--md", required=True)
    a = p.parse_args(argv)
    comps, _ = gen.read_netlist(a.netlist)
    rs = rows(comps)
    for r in rs:
        if not r["DNP"] and not r["LCSC"]:
            raise SystemExit("bom: %s has no LCSC part number" % r["Refs"])
    with open(a.csv, "w", encoding="utf-8") as f:
        f.write(to_csv(rs))
    with open(a.md, "w", encoding="utf-8") as f:
        f.write(to_md(rs))


if __name__ == "__main__":
    main(sys.argv[1:])
