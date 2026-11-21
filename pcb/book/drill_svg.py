# SPDX-License-Identifier: Apache-2.0
"""drill_svg --drill DIR --mech JSON --out SVG: the board's holes, for the
book's fab chapter, from the Excellon files //pcb:drill writes.

Each hole is a filled circle at its drilled size, coloured by tool; slots
(G85) are drawn as strokes of their width with round ends. The board's
outline and its Edge.Cuts slots come from mech/mechanics.bzl (as
pcb/gen.py draws them). The drawing has no text: svgpng draws no text,
and the book adds its legend. Y grows down in SVG; the board's frame has
Y up, so it is flipped.
"""

import argparse
import glob
import json
import os
import re
import sys

import gen
import placement

# One colour per tool, in the order of the tools' diameters.
COLOURS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#e377c2", "#17becf"]

TOOL = re.compile(r"^T(\d+)C([0-9.]+)")
SELECT = re.compile(r"^T(\d+)$")
POINT = re.compile(r"^X(-?[0-9.]+)Y(-?[0-9.]+)$")
SLOT = re.compile(r"^X(-?[0-9.]+)Y(-?[0-9.]+)G85X(-?[0-9.]+)Y(-?[0-9.]+)$")


def holes(text):
    """[(diameter, x1, y1, x2, y2)] of an Excellon file in decimal mm, in
    its own coordinates; x2, y2 equal x1, y1 for a round hole."""
    tools, out, tool, body = {}, [], None, False
    for line in text.splitlines():
        line = line.strip()
        if line == "%":
            body = True
            continue
        if not body:
            m = TOOL.match(line)
            if m:
                tools[m.group(1)] = float(m.group(2))
            elif line.startswith("INCH"):
                raise ValueError("an Excellon file in inches; want METRIC")
            continue
        m = SELECT.match(line)
        if m:
            if m.group(1) != "0" and m.group(1) not in tools:
                raise ValueError("tool T%s is not defined" % m.group(1))
            tool = m.group(1)
            continue
        m = SLOT.match(line) or POINT.match(line)
        if m:
            if tool not in tools:
                raise ValueError("a hole before any tool: %s" % line)
            v = [float(g) for g in m.groups()]
            out.append((tools[tool], v[0], v[1], v[-2], v[-1]))
    return out


def svg(found, mech):
    board = mech["BOARD"]
    length, width = board["length"], board["width"]

    def bx(x):
        return x - gen.ORIGIN_X

    def by(y):
        # Excellon's Y is KiCad's page Y negated (the page's Y grows
        # down); pcb/gen.py puts board y at page ORIGIN_Y + width - y.
        return gen.ORIGIN_Y + width + y

    for d, x1, y1, x2, y2 in found:
        for x, y in ((bx(x1), by(y1)), (bx(x2), by(y2))):
            if not (0 <= x <= length and 0 <= y <= width):
                raise ValueError("a %.3f mm hole at (%.3f, %.3f) in the board's frame, outside the board" % (d, x, y))

    sizes = sorted({h[0] for h in found})
    colour = {d: COLOURS[i % len(COLOURS)] for i, d in enumerate(sizes)}
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">' % (length, width, length, width),
        '<rect x="0" y="0" width="%g" height="%g" fill="#f4f1e8" stroke="#555555" stroke-width="0.15"/>' % (length, width),
    ]
    for x1, y1, x2, y2, w in placement.slots(mech):
        out.append(
            '<line x1="%.4f" y1="%.4f" x2="%.4f" y2="%.4f" stroke="#555555" stroke-width="%g" stroke-linecap="round"/>'
            % (x1, width - y1, x2, width - y2, w)
        )
    for d, x1, y1, x2, y2 in sorted(found):
        c = colour[d]
        if (x1, y1) == (x2, y2):
            out.append('<circle cx="%.4f" cy="%.4f" r="%.4f" fill="%s"/>' % (bx(x1), width - by(y1), d / 2, c))
        else:
            out.append(
                '<line x1="%.4f" y1="%.4f" x2="%.4f" y2="%.4f" stroke="%s" stroke-width="%.4f" stroke-linecap="round"/>'
                % (bx(x1), width - by(y1), bx(x2), width - by(y2), c, d)
            )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--drill", required=True, help="//pcb:drill's directory")
    ap.add_argument("--mech", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.drill, "*.drl")))
    if not files:
        sys.stderr.write("drill_svg: no .drl file in %s\n" % a.drill)
        return 1
    found = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            found += holes(fh.read())
    if not found:
        sys.stderr.write("drill_svg: no hole in %s\n" % ", ".join(files))
        return 1
    with open(a.mech, encoding="utf-8") as fh:
        mech = json.load(fh)
    try:
        text = svg(found, mech)
    except ValueError as e:
        sys.stderr.write("drill_svg: %s\n" % e)
        return 1
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
