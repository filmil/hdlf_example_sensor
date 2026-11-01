# SPDX-License-Identifier: Apache-2.0
"""The enclosure's tray, 3D-printed: a box open at the top, with four bosses
that the board screws to, four corner posts that the front panel screws
to, a cut-out for the USB-C plug, and vents by the sensor.

Its frame: the outside's lower-left corner at the origin, the floor's
bottom at Z 0. The board sits on the bosses, its lower-left corner at
(wall + gap_x, wall + gap_y); mechanics.bzl has the numbers.
"""

from build123d import Align, Box, Cylinder, Pos

MIN = (Align.MIN, Align.MIN, Align.MIN)
CTR = (Align.CENTER, Align.CENTER, Align.MIN)


def build(p):
    L, W, T = p["board_length"], p["board_width"], p["board_thickness"]
    wall, floor = p["enclosure_wall"], p["enclosure_floor"]
    gx, gy = p["enclosure_gap_x"], p["enclosure_gap_y"]
    boss_h, inner_h = p["enclosure_boss_height"], p["enclosure_inner_height"]
    il, iw = L + 2 * gx, W + 2 * gy
    ol, ow, oh = il + 2 * wall, iw + 2 * wall, floor + inner_h

    tray = Box(ol, ow, oh, align=MIN) - Pos(wall, wall, floor) * Box(il, iw, inner_h + 1, align=MIN)

    # The board's mounting bosses, each with a pilot hole down to the floor.
    bx, by = wall + gx, wall + gy
    for hx, hy in p["holes"]:
        at = Pos(bx + hx, by + hy, floor)
        tray += at * Cylinder(p["enclosure_boss_d"] / 2, boss_h, align=CTR)
        tray -= at * Cylinder(p["enclosure_pilot_d"] / 2, boss_h, align=CTR)

    # The panel's screw posts, in the inside corners, up to the rim.
    r = p["enclosure_post_d"] / 2
    for cx in (wall + r, ol - wall - r):
        for cy in (wall + r, ow - wall - r):
            at = Pos(cx, cy, floor)
            tray += at * Cylinder(r, inner_h, align=CTR)
            tray -= at * Cylinder(p["enclosure_pilot_d"] / 2, inner_h, align=CTR)

    # The USB-C plug's way in, through the left wall, around the receptacle.
    m = p["enclosure_usb_margin"]
    top = floor + boss_h + T
    uw, uh = p["usb_width"] + 2 * m, p["usb_height"] + 2 * m
    tray -= Pos(-1, by + p["usb_y"] - uw / 2, top - m) * Box(wall + 2, uw, uh, align=MIN)

    # Vents in the right wall, by the sensor: four slots.
    for i in range(4):
        tray -= Pos(ol - wall - 1, by + 4 + i * 5, floor + 4) * Box(wall + 2, 2, 6, align=MIN)
    return tray
