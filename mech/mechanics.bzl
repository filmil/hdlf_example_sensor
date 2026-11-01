# SPDX-License-Identifier: Apache-2.0
"""The mechanical interface of the design: one source for the numbers that
the board, the enclosure and the front panel share. The enclosure reads them
now; the board's generator and the front panel will, from their own pull
requests on.

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
# A mating plug's overmold is at most 12.35 x 6.5 mm (USB Type-C cable and
# connector specification, the plug's overmold envelope).
USB = {
    "y": 12.5,
    "width": 8.94,  # the receptacle's body, across
    "height": 3.26,  # above the board's top
    "length": 7.35,  # from the board's edge inwards
    "plug_width": 12.35,
    "plug_height": 6.5,
    "plug_length": 20.0,  # the overmold, from the receptacle's mouth outwards
}

# The temperature and humidity sensor, on the board's top, at the end away
# from the warm parts; the tray's vents face it.
SENSOR = {
    "x": 37.0,
    "y": 12.5,
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
    "floor": 2.4,
    "gap_x": 1.0,  # board to the tray's ends: the USB-C plug reaches the receptacle
    "gap_y": 8.0,  # board to the tray's sides: room for the panel's corner posts
    "boss_height": 4.0,  # floor to the board's bottom
    "boss_d": 5.5,
    "pilot_d": 2.2,  # M2.5 self-tapping into PETG
    "inner_height": 13.0,  # floor to the tray's rim
    "post_d": 6.0,  # the panel's screw posts, in the corners
    "usb_margin": 0.4,  # around the plug's overmold
    "pilot_depth": 0.8,  # into the floor, leaving 1.6 mm under it (min_wall 1.5)
    "vent_count": 4,
    "vent_pitch": 4.0,
    "vent_width": 2.0,
    "vent_height": 4.5,  # leaves 1.9 mm of rim above them (min_wall 1.5)
    "vent_above_board": 1.0,  # from the board's top to the vents' bottom
    "post_pilot_depth": 8.0,  # the panel's screws, from the rim down
}

# The front panel: 2 mm aluminium (6061), the tray's outside in XY.
PANEL = {
    "thickness": 2.0,
    "screw_d": 2.7,  # M2.5 clearance, over the tray's posts
    "led_d": 3.2,  # over the LED, for a 3 mm light pipe
    "label_length": 24.0,  # the recessed label area
    "label_width": 8.0,
    "label_depth": 0.3,
    "label_y": 34.0,  # its center, from the panel's front edge (Y 0)
}

def check_enclosure():
    """Fails the build when the enclosure's numbers cannot work together."""
    e = ENCLOSURE
    if e["post_pilot_depth"] > e["inner_height"] - 1.5:
        fail("post_pilot_depth %s leaves less than 1.5 mm under it in a %s mm post" % (e["post_pilot_depth"], e["inner_height"]))
    if e["pilot_depth"] > e["floor"] - 1.5:
        fail("pilot_depth %s leaves less than 1.5 mm of a %s mm floor" % (e["pilot_depth"], e["floor"]))

def led_center():
    """The LED's center in the tray's (and the panel's) frame, XY."""
    e = ENCLOSURE
    return [e["wall"] + e["gap_x"] + LED["x"], e["wall"] + e["gap_y"] + LED["y"]]

def panel_placement():
    """Where the panel sits: on the tray's rim."""
    return '{"pos": [0, 0, %s]}' % outer_size()[2]

def outer_size():
    """The tray's outside, [X, Y, Z] in mm."""
    e, b = ENCLOSURE, BOARD
    return [
        b["length"] + 2 * e["gap_x"] + 2 * e["wall"],
        b["width"] + 2 * e["gap_y"] + 2 * e["wall"],
        e["floor"] + e["inner_height"],
    ]

def post_centers():
    """The front panel's screw posts, in the tray's frame (XY): one in each
    inside corner, overlapping both walls by a third of its radius so that it
    is part of them."""
    ol, ow, _ = outer_size()
    c = ENCLOSURE["wall"] + ENCLOSURE["post_d"] / 2 * 2 / 3
    return [[c, c], [ol - c, c], [c, ow - c], [ol - c, ow - c]]

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
