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
    # "grow" makes it larger on every side but the mouth: the margin test.
    g = p.get("grow", 0)
    w, h, length = p["usb_plug_width"] + 2 * g, p["usb_plug_height"] + 2 * g, p["usb_plug_length"]
    zc = T + p["usb_height"] / 2
    return Pos(-length, p["usb_y"] - w / 2, zc - h / 2) * Box(length, w, h, align=(Align.MIN, Align.MIN, Align.MIN))
