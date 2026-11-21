# SPDX-License-Identifier: Apache-2.0
"""book_png --svgpng TOOL --width PX IN OUT: draws an SVG as a PNG exactly
PX pixels wide. svgpng takes dots per inch, and KiCad's plot of a board's
area is wider than the board itself (parts overhang its edge), so this
reads the SVG's width in mm and gives svgpng the matching dpi."""

import argparse
import re
import subprocess
import sys

# The <svg> element's own width attribute: after white space, so that
# stroke-width and the like never match.
WIDTH = re.compile(r'<svg\s[^>]*\swidth="([0-9.]+)mm"', re.S)


def dpi_for(svg_text, px):
    """The dpi at which svgpng draws the SVG px pixels wide: svgpng makes
    it round(width_mm * dpi / 25.4) pixels, so a dpi correct to 6 decimals
    gives px exactly."""
    if px <= 0:
        raise ValueError("a width of %d pixels" % px)
    m = WIDTH.search(svg_text)
    if not m:
        raise ValueError("the SVG has no width in mm")
    mm = float(m.group(1))
    if mm <= 0:
        raise ValueError("the SVG is %s mm wide" % m.group(1))
    return px * 25.4 / mm


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--svgpng", required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("src")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    with open(a.src, encoding="utf-8") as f:
        try:
            dpi = dpi_for(f.read(), a.width)
        except ValueError as e:
            sys.stderr.write("book_png: %s: %s\n" % (a.src, e))
            return 1
    return subprocess.call([a.svgpng, "--dpi", "%.6f" % dpi, a.src, a.out])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
