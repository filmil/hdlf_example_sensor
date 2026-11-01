# SPDX-License-Identifier: Apache-2.0
"""Adds one track to a routed board, for a known-bad test.

    spoil.py --in B.kicad_pcb --out S.kicad_pcb --net NAME \\
        --start X Y --end X Y \\
        --project_in B.kicad_pro --project_out S.kicad_pro [--ignore TYPE ...]

The track is on F.Cu, 0.2 mm wide, on the board's net NAME, from start to
end on KiCad's page (mm). Everything else stays as it was. The project is
the board's, with each --ignore violation type set to "ignore", so a
known-bad DRC test sees only the violation it is about.
"""

import argparse
import hashlib
import json
import sys

import sexpr
from sexpr import A, L, Q


def spoil(text, net, start, end):
    board = sexpr.parse(text)
    codes = {n.arg(1): n.arg(0) for n in board.children("net")}
    if net not in codes:
        raise SystemExit("spoil: the board has no net %r" % net)
    h = hashlib.sha256(("spoil %s %s %s" % (net, start, end)).encode()).hexdigest()
    uuid = "%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])
    board.items.append(L(
        "segment", L("start", A(start[0]), A(start[1])), L("end", A(end[0]), A(end[1])),
        L("width", A("0.2")), L("layer", Q("F.Cu")), L("net", A(codes[net])), L("uuid", Q(uuid))))
    return sexpr.write(board) + "\n"


def project(text, ignore):
    pro = json.loads(text)
    sev = pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})
    for t in ignore:
        sev[t] = "ignore"
    return json.dumps(pro, indent=2, sort_keys=True) + "\n"


def main(argv):
    p = argparse.ArgumentParser(prog="spoil")
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--net", required=True)
    p.add_argument("--start", nargs=2, required=True)
    p.add_argument("--end", nargs=2, required=True)
    p.add_argument("--project_in", required=True)
    p.add_argument("--project_out", required=True)
    p.add_argument("--ignore", action="append", default=[])
    a = p.parse_args(argv)
    with open(a.inp, encoding="utf-8") as f:
        text = f.read()
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(spoil(text, a.net, a.start, a.end))
    with open(a.project_in, encoding="utf-8") as f:
        pro = f.read()
    with open(a.project_out, "w", encoding="utf-8") as f:
        f.write(project(pro, a.ignore))


if __name__ == "__main__":
    main(sys.argv[1:])
