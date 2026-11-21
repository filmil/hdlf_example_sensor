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

TOOL = re.compile(r"^T(\d+)C(\d*\.\d+)$")
SELECT = re.compile(r"^T(\d+)$")
# The body commands kicad_drill writes that place no hole: absolute
# coordinates, drill mode, end of program. Anything else is refused, so a
# hole in a form this reader does not know is never left out.
QUIET = {"G90", "G05", "M30"}
# Decimal coordinates only: a fixed-point file (no decimal point) would
# be read at the wrong scale.
_N = r"(-?\d*\.\d+)"
POINT = re.compile(r"^X%sY%s$" % (_N, _N))
SLOT = re.compile(r"^X%sY%sG85X%sY%s$" % (_N, _N, _N, _N))
# The header lines kicad_drill writes that define no tool: the start,
# the format version, and the units (decimal millimetres). Anything else
# in the header (INCH, METRIC,TZ, ICI,ON, G91, ...) is refused.
HEADER = {"M48", "FMAT,2", "METRIC"}


def holes(text):
    """[(diameter, x1, y1, x2, y2)] of an Excellon file in decimal mm, in
    its own coordinates; x2, y2 equal x1, y1 for a round hole. Tools are
    numbers (T01 is T1); T0 unloads the tool."""
    tools, out, tool, body, metric = {}, [], None, False, False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line == "%":
            body = True
            continue
        if not body:
            m = TOOL.match(line)
            if m:
                t, d = int(m.group(1)), float(m.group(2))
                if t == 0 or t in tools or d <= 0:
                    raise ValueError("a bad tool definition (T0, a tool twice, or no diameter): %s" % line)
                tools[t] = d
            elif line in HEADER:
                metric = metric or line == "METRIC"
            else:
                raise ValueError("an Excellon header line this reader does not know: %s" % line)
            continue
        m = SELECT.match(line)
        if m:
            t = int(m.group(1))
            if t != 0 and t not in tools:
                raise ValueError("tool T%s is not defined" % m.group(1))
            tool = t or None
            continue
        m = SLOT.match(line) or POINT.match(line)
        if m:
            if tool is None:
                raise ValueError("a hole with no tool: %s" % line)
            v = [float(g) for g in m.groups()]
            out.append((tools[tool], v[0], v[1], v[-2], v[-1]))
            continue
        if line not in QUIET:
            raise ValueError("an Excellon command this reader does not know: %s" % line)
    if not body:
        raise ValueError("an Excellon file with no % ending its header")
    if not metric:
        raise ValueError("an Excellon file without METRIC in its header")
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
    if len(sizes) > len(COLOURS):
        raise ValueError("%d drill sizes, but only %d colours" % (len(sizes), len(COLOURS)))
    colour = {d: COLOURS[i] for i, d in enumerate(sizes)}
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
    try:
        for f in files:
            with open(f, encoding="utf-8") as fh:
                found += holes(fh.read())
        if not found:
            raise ValueError("no hole in %s" % ", ".join(files))
        with open(a.mech, encoding="utf-8") as fh:
            mech = json.load(fh)
        text = svg(found, mech)
    except ValueError as e:
        sys.stderr.write("drill_svg: %s\n" % e)
        return 1
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
