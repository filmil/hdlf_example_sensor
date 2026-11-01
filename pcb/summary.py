# SPDX-License-Identifier: Apache-2.0
"""The fab package as a page for people: what JLCPCB gets, and the order.

    summary.py --zip P.zip --mech mech.json --bom BOM.md --out S.md
"""

import argparse
import json
import sys
import zipfile


def summary(zip_path, mech, bom_md):
    B = mech["BOARD"]
    out = ["# JLCPCB package of the sensor board", "",
           "| Order setting | Value |", "|---|---|",
           "| Size | %g x %g mm |" % (B["length"], B["width"]),
           "| Layers | 2 |",
           "| Thickness | %g mm |" % B["thickness"],
           "| Copper | 1 oz outer |",
           "| Assembly | top side only |",
           "", "## Files", "", "| File | Bytes |", "|---|---:|"]
    with zipfile.ZipFile(zip_path) as z:
        for i in sorted(z.infolist(), key=lambda i: i.filename):
            out.append("| %s | %d |" % (i.filename, i.file_size))
    out += ["", "## Parts", ""]
    body = bom_md.split("\n", 2)[2] if bom_md.startswith("# ") else bom_md
    out.append(body.strip())
    return "\n".join(out) + "\n"


def main(argv):
    p = argparse.ArgumentParser(prog="summary")
    p.add_argument("--zip", required=True)
    p.add_argument("--mech", required=True)
    p.add_argument("--bom", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    with open(a.mech, encoding="utf-8") as f:
        mech = json.load(f)
    with open(a.bom, encoding="utf-8") as f:
        bom_md = f.read()
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(summary(a.zip, mech, bom_md))


if __name__ == "__main__":
    main(sys.argv[1:])
