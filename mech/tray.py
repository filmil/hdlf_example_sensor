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
    pilot_r, pilot_depth = p["enclosure_pilot_d"] / 2, p["enclosure_pilot_depth"]
    il, iw = L + 2 * gx, W + 2 * gy
    ol, ow, oh = p["outer"]

    tray = Box(ol, ow, oh, align=MIN) - Pos(wall, wall, floor) * Box(il, iw, inner_h + 1, align=MIN)

    # A pilot hole: from pilot_depth into the floor to above its boss or
    # post, so no cut ends on a face it cuts; an M2.5 x 6 screw through the
    # board or the panel has room.
    def pilot(x, y, height):
        return Pos(x, y, floor - pilot_depth) * Cylinder(pilot_r, pilot_depth + height + 1, align=CTR)

    # A post's pilot: from post_pilot_depth below the rim to above it; the
    # panel's screw comes from the top.
    def post_pilot(x, y):
        d = p["enclosure_post_pilot_depth"]
        return Pos(x, y, oh - d) * Cylinder(pilot_r, d + 1, align=CTR)

    # The board's mounting bosses.
    bx, by = wall + gx, wall + gy
    for hx, hy in p["holes"]:
        tray += Pos(bx + hx, by + hy, floor) * Cylinder(p["enclosure_boss_d"] / 2, boss_h, align=CTR)
        tray -= pilot(bx + hx, by + hy, boss_h)

    # The front panel's screw posts, in the corners and part of the walls.
    for cx, cy in p["posts"]:
        tray += Pos(cx, cy, floor) * Cylinder(p["enclosure_post_d"] / 2, inner_h, align=CTR)
        tray -= post_pilot(cx, cy)

    # The USB-C plug's way in, through the left wall: the plug's overmold,
    # centered on the receptacle, with a margin.
    m = p["enclosure_usb_margin"]
    top = floor + boss_h + T
    zc = top + p["usb_height"] / 2
    pw, ph = p["usb_plug_width"] + 2 * m, p["usb_plug_height"] + 2 * m
    # It runs from outside the wall to the board's edge, where the plug
    # meets the receptacle, whatever gap_x is.
    tray -= Pos(-1, by + p["usb_y"] - pw / 2, zc - ph / 2) * Box(wall + gx + 1, pw, ph, align=MIN)

    # Vents in the right wall, facing the sensor, above the board.
    n, pitch = p["enclosure_vent_count"], p["enclosure_vent_pitch"]
    vw, vh = p["enclosure_vent_width"], p["enclosure_vent_height"]
    y0 = by + p["sensor_y"] - ((n - 1) * pitch + vw) / 2
    for i in range(n):
        tray -= Pos(ol - wall - 1, y0 + i * pitch, top + p["enclosure_vent_above_board"]) * Box(wall + 2, vw, vh, align=MIN)
    return tray
