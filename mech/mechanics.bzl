# SPDX-License-Identifier: Apache-2.0
"""The mechanical interface of the design: one source for the board and the
enclosure, so they cannot drift apart.

All sizes are in mm. The board's frame: its lower-left corner at the
origin, its bottom face at Z 0, X along its long side.
"""

# The board: size, and its four M2.5 mounting holes, one at each corner.
BOARD = {
    "length": 40.0,
    "width": 25.0,
    "thickness": 1.6,
    "hole_d": 2.7,  # M2.5 clearance
    "hole_inset": 3.5,  # from each edge to a hole's center
}

# The USB-C receptacle: centered on the board's left (X 0) edge, on top.
USB = {
    "y": 12.5,
    "width": 8.94,  # the receptacle's body, across
    "height": 3.26,  # above the board's top
}

# The status LED, on the board's top, seen through the front panel.
LED = {
    "x": 33.0,
    "y": 12.5,
}

def board_holes():
    """The mounting holes' centers, in the board's frame."""
    l, w, i = BOARD["length"], BOARD["width"], BOARD["hole_inset"]
    return [[i, i], [l - i, i], [i, w - i], [l - i, w - i]]

# The enclosure: a printed tray, closed by the milled front panel.
ENCLOSURE = {
    "wall": 2.0,
    "floor": 2.0,
    "gap_x": 1.0,  # board to the tray's ends: the USB-C plug reaches the receptacle
    "gap_y": 8.0,  # board to the tray's sides: room for the panel's corner posts
    "boss_height": 4.0,  # floor to the board's bottom
    "boss_d": 5.5,
    "pilot_d": 2.2,  # M2.5 self-tapping into PETG
    "inner_height": 13.0,  # floor to the tray's rim
    "post_d": 6.0,  # the panel's screw posts, in the corners
    "usb_margin": 0.6,  # around the receptacle, for the plug's overmold
}

def board_placement():
    """Where the board sits in the tray's frame, as cad_assembly's JSON."""
    e = ENCLOSURE
    return '{"pos": [%s, %s, %s]}' % (e["wall"] + e["gap_x"], e["wall"] + e["gap_y"], e["floor"] + e["boss_height"])

def params(**dicts):
    """cad_part params: each dict's entries as JSON strings, named
    "<dict>_<key>": params(board = BOARD) gives "board_length" and so on."""
    out = {}
    for name, d in dicts.items():
        for k, v in d.items():
            out[name + "_" + k] = json.encode(v)
    return out
