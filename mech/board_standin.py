# SPDX-License-Identifier: Apache-2.0
"""A stand-in for the circuit board, until the board's own STEP model (from
hdlf_rules_kicad) replaces it: the board's outline and mounting holes, and
the USB-C receptacle's body, the tallest part at the edge.

Its frame is the board's: lower-left corner at the origin, bottom at Z 0.
"""

from build123d import Align, Box, Cylinder, Pos

MIN = (Align.MIN, Align.MIN, Align.MIN)
CTR = (Align.CENTER, Align.CENTER, Align.MIN)


def build(p):
    L, W, T = p["board_length"], p["board_width"], p["board_thickness"]
    board = Box(L, W, T, align=MIN)
    for hx, hy in p["holes"]:
        board -= Pos(hx, hy, 0) * Cylinder(p["board_hole_d"] / 2, T, align=CTR)
    usb = Pos(0, p["usb_y"] - p["usb_width"] / 2, T) * Box(7.35, p["usb_width"], p["usb_height"], align=MIN)
    return board + usb
