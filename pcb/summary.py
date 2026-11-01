# SPDX-License-Identifier: Apache-2.0
"""The fab package as a page for people: what JLCPCB gets, and the order.

    summary.py --zip P.zip --mech mech.json --stackup 2L-1oz --bom BOM.md \\
        --out S.md

The layer count and the assembled sides come from the package itself (its
copper Gerbers and its placement list), the copper weight from the stackup
fab_rules uses, and the size from mechanics.bzl, so the page cannot drift
from what is ordered.
"""

import argparse
import csv
import io
import json
import re
import sys
import zipfile


def _cell(text):
    return " ".join(text.split()).replace("|", "\\|")


def summary(zip_path, mech, stackup, bom_md):
    B = mech["BOARD"]
    with zipfile.ZipFile(zip_path) as z:
        files = sorted((i for i in z.infolist() if not i.is_dir()), key=lambda i: i.filename)
        copper = [i.filename for i in files if re.search(r"[-_](F|B|In\d+)_Cu\.", i.filename)]
        sides = set()
        for i in files:
            if i.filename.endswith("_cpl.csv"):
                for row in csv.DictReader(io.StringIO(z.read(i).decode("utf-8"))):
                    sides.add(row.get("Layer", ""))
    m = re.match(r"(\d+)L-(\S+)$", stackup)
    if not m:
        raise SystemExit("summary: stackup %r is not like 2L-1oz" % stackup)
    if int(m.group(1)) != len(copper):
        raise SystemExit("summary: stackup %s, but the package has %d copper layer(s)" % (stackup, len(copper)))
    assembly = " and ".join(sorted(s.lower() for s in sides if s)) + " side" if sides else "none"
    out = ["# JLCPCB package of the sensor board", "",
           "| Order setting | Value |", "|---|---|",
           "| Size | %g x %g mm |" % (B["length"], B["width"]),
           "| Layers | %d |" % len(copper),
           "| Thickness | %g mm |" % B["thickness"],
           "| Copper | %s outer |" % m.group(2),
           "| Assembly | %s |" % assembly,
           "", "## Files", "", "| File | Bytes |", "|---|---:|"]
    for i in files:
        out.append("| %s | %d |" % (_cell(i.filename), i.file_size))
    out += ["", "## Parts", ""]
    lines = bom_md.split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    out.append("\n".join(lines).strip())
    return "\n".join(out) + "\n"


def main(argv):
    p = argparse.ArgumentParser(prog="summary")
    p.add_argument("--zip", required=True)
    p.add_argument("--mech", required=True)
    p.add_argument("--stackup", required=True)
    p.add_argument("--bom", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    with open(a.mech, encoding="utf-8") as f:
        mech = json.load(f)
    with open(a.bom, encoding="utf-8") as f:
        bom_md = f.read()
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(summary(a.zip, mech, a.stackup, bom_md))


if __name__ == "__main__":
    main(sys.argv[1:])
