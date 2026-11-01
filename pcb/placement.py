# SPDX-License-Identifier: Apache-2.0
"""Where each part goes: (x, y, rotation) in the board's frame (mm, Y up,
lower-left corner at the origin; rotation in degrees, KiCad's sense).

The USB-C receptacle, the LED and the sensor take their places from
mech/mechanics.bzl; the rest are placed here, near the pins they serve.
"""

HOLE_FOOTPRINT = "MountingHole:MountingHole_2.7mm_M2.5"

# No copper within this radius of a hole's center, on either side: an M2.5
# pan head is about 4.5 mm across, and the footprint's courtyard is 2.7 mm.
# gen.py draws the keep-out as a 16-sided polygon around this circle, so
# its corners reach 2.75 mm.
SCREW_HEAD_KEEPOUT_R = 2.7

# The receptacle's mouth is its footprint's +Y side, 3.675 mm from its
# origin (the "PCB Edge" line of USB_C_Receptacle_GCT_USB4105-xx-A_16P,
# and mechanics.bzl's USB length 7.35 / 2); turned 270 degrees, the mouth
# faces the board's left edge.
_USB_EDGE = 3.675


def positions(mech):
    usb, led, sensor = mech["USB"], mech["LED"], mech["SENSOR"]
    return {
        # Power and USB, at the left.
        "J1": (_USB_EDGE, usb["y"], 270),
        "U4": (12.0, 12.5, 0),
        "R1": (11.0, 16.2, 0),
        "R2": (11.0, 8.8, 0),
        "U2": (14.5, 19.3, 180),
        "C1": (11.0, 19.3, 90),
        "C2": (18.0, 19.3, 90),
        # The microcontroller, pins 11 to 20 facing the USB side.
        "U1": (20.0, 12.5, 180),
        "C3": (18.6, 6.8, 0),
        "C4": (21.6, 6.8, 0),
        "C5": (25.6, 13.6, 0),
        "C6": (25.6, 15.4, 0),
        "C7": (25.6, 11.4, 0),
        "R5": (26.0, 9.6, 0),
        "JP1": (26.0, 7.6, 0),
        "R3": (28.6, 9.0, 90),
        "R4": (28.6, 16.0, 90),
        # The SWD header, along the bottom edge.
        "J2": (13.0, 3.6, 90),
        # The LED and its resistor; the sensor and its capacitor, beyond
        # the slot.
        "R6": (29.8, 12.5, 0),
        "D1": (led["x"], led["y"], 0),
        "U3": (sensor["x"], sensor["y"], 90),
        "C8": (sensor["x"], 16.6, 0),
    }


def slots(mech):
    """Edge.Cuts slots (x1, y1, x2, y2, width): one between the LED and the
    sensor, so that the warm side's heat reaches the sensor only through
    the board above and below it."""
    s = mech["SENSOR"]
    x = (mech["LED"]["x"] + s["x"]) / 2 + 0.2
    return [(x, s["y"] - 3.4, x, s["y"] + 3.4, 1.0)]


def keepouts(mech):
    """Rule areas around the sensor: (name, layer, half width, half height),
    centered on it. Its pad rows run along X at Y +-1.4 (the footprint
    turned 90 degrees); the top area stays between them, clear of the
    pads (0.75 mm long), and the bottom one covers the 3 x 3 mm package."""
    return [
        ("U3 top keepout", "F.Cu", 1.6, 0.9),
        ("U3 bottom keepout", "B.Cu", 2.0, 2.0),
    ]
