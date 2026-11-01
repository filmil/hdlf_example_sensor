# SPDX-License-Identifier: Apache-2.0
"""The front panel: a milled 2 mm aluminium plate that closes the tray.
Four holes for the screws into the tray's corner posts, one over the
status LED for a light pipe, and a shallow recessed label area.

Its frame is the tray's, at the panel's bottom: Z 0 is the face that rests
on the tray's rim.
"""

from build123d import Align, Box, Cylinder, Pos

MIN = (Align.MIN, Align.MIN, Align.MIN)
CTR = (Align.CENTER, Align.CENTER, Align.MIN)


def build(p):
    ol, ow, _ = p["outer"]
    t = p["panel_thickness"]
    panel = Box(ol, ow, t, align=MIN)
    for x, y in p["posts"]:
        panel -= Pos(x, y, -1) * Cylinder(p["panel_screw_d"] / 2, t + 2, align=CTR)
    lx, ly = p["led"]
    panel -= Pos(lx, ly, -1) * Cylinder(p["panel_led_d"] / 2, t + 2, align=CTR)
    ll, lw, ld = p["panel_label_length"], p["panel_label_width"], p["panel_label_depth"]
    panel -= Pos(ol / 2 - ll / 2, p["panel_label_y"] - lw / 2, t - ld) * Box(ll, lw, ld + 1, align=MIN)
    return panel
