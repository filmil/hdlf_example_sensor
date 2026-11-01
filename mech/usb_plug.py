# SPDX-License-Identifier: Apache-2.0
"""A USB-C cable's plug, mated: its overmold at the specification's largest
(12.35 x 6.5 mm), from the receptacle's mouth outwards. The enclosure's
interference test places it, to show that a real cable fits through the
tray's cut-out.

Its frame is the board's, as for the receptacle: the mouth at X 0, the
plug running to negative X, centered on the receptacle.
"""

from build123d import Align, Box, Pos


def build(p):
    T = p["board_thickness"]
    # The margin tests: "grow" makes it larger across (in Y and Z), on
    # every side, or with "grow_side" (y-, y+, z- or z+) on that one only.
    g = p.get("grow", 0)
    side = p.get("grow_side")
    w, h, length = p["usb_plug_width"], p["usb_plug_height"], p["usb_plug_length"]
    zc = T + p["usb_height"] / 2
    y0, y1 = p["usb_y"] - w / 2, p["usb_y"] + w / 2
    z0, z1 = zc - h / 2, zc + h / 2
    if side is None:
        y0, y1, z0, z1 = y0 - g, y1 + g, z0 - g, z1 + g
    elif side == "y-":
        y0 -= g
    elif side == "y+":
        y1 += g
    elif side == "z-":
        z0 -= g
    elif side == "z+":
        z1 += g
    else:
        raise ValueError("grow_side %r: not y-, y+, z- or z+" % side)
    return Pos(-length, y0, z0) * Box(length, y1 - y0, z1 - z0, align=(Align.MIN, Align.MIN, Align.MIN))
