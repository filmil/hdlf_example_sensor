# SPDX-License-Identifier: Apache-2.0
"""Stand-ins for what passes through the front panel: its four screws and
the LED's light pipe. In the closed enclosure's interference test they
show that the panel's holes line up with the tray's pilots and the LED.

A screw is its shank (screw_shank_d) through the panel, and its core, just
under the pilot, below: off by more than a few hundredths of a millimetre,
it cuts the panel or the post. The light pipe runs from the panel's top to
1 mm above the board, over the LED.

Its frame is the tray's.
"""

from build123d import Align, Cylinder, Pos

CTR = (Align.CENTER, Align.CENTER, Align.MIN)


def build(p):
    _, _, oh = p["outer"]
    t = p["panel_thickness"]
    top = oh + t
    e = 0.05  # less than any hole, so that only a misplaced one overlaps
    parts = []
    for x, y in p["posts"]:
        parts.append(Pos(x, y, oh) * Cylinder(p["panel_screw_shank_d"] / 2, t, align=CTR))
        core = p["panel_screw_length"] - t
        parts.append(Pos(x, y, oh - core) * Cylinder(p["enclosure_pilot_d"] / 2 - e, core, align=CTR))
    lx, ly = p["led"]
    board_top = p["enclosure_floor"] + p["enclosure_boss_height"] + p["board_thickness"]
    pipe = top - (board_top + 1.0)
    parts.append(Pos(lx, ly, board_top + 1.0) * Cylinder(p["panel_light_pipe_d"] / 2, pipe, align=CTR))
    out = parts[0]
    for s in parts[1:]:
        out += s
    return out
