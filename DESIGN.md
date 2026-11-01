<!-- SPDX-License-Identifier: Apache-2.0 -->
# The design

A small USB-C sensor that reports temperature and relative humidity. It is
the worked example of the hdlf_rules_* user manual, so it uses every module
for real, and each part of it is built, checked and drawn by Bazel.

## Electrical (hdlf_rules_netlist, hdlf_rules_kicad)

* A USB 2.0 device, powered and connected by one USB-C receptacle (5.1 kΩ
  CC pull-downs, so a USB-C host gives it 5 V).
* A 3.3 V low-dropout regulator.
* A microcontroller with native USB.
* An I²C temperature and humidity sensor, placed away from the regulator
  and the microcontroller, the board's warm parts.
* One status LED, seen through the front panel.
* A programming header, if the microcontroller needs one.
* The supporting parts each of these needs, as its datasheet says:
  decoupling and bulk capacitors (within USB's limit on VBUS capacitance),
  I²C pull-ups, the LED's resistor, and ESD protection on the USB lines.

The circuit is written as code (SKiDL), and `netlist_parity_test` checks the
board's connections against it. Every part is a real, orderable one, with
its LCSC number and datasheet; none is invented.

`elec/parts.py` lists the parts, as #5 chose them: an STM32F042F6P6
(crystal-less USB), an XC6206P332MR regulator, an HDC2080 sensor at I²C
address 0x40, a GCT USB4105 receptacle, a USBLC6-2SC6 for ESD, and 0603
passives and LED. `elec/circuit.py` connects them, citing the datasheet
page for each connection, and fails the build on any SKiDL ERC error or
warning, or on a part that lacks its LCSC number, MPN, maker or
datasheet. The microcontroller programs over USB (DFU) with the BOOT0
solder jumper closed, or over SWD from the 4-pin header, which the
assembly service does not fit.

## The board (hdlf_rules_kicad, hdlf_rules_fab)

* About 40 × 25 mm, 2 layers, 1.6 mm thick.
* Four M2.5 mounting holes, one at each corner.
* The USB-C receptacle at one short edge; the sensor near the other.
* DRC with JLCPCB's rules; Gerbers, drill files, positions and the BOM;
  a STEP model with the parts' 3D models; renders of both sides.
* A JLCPCB assembly package, checked by `fab_package_test`.

## Mechanical (hdlf_rules_brep)

`mech/mechanics.bzl` holds the numbers the board, the enclosure and the
front panel share: the board's size and holes, where the USB-C receptacle,
the sensor and the LED are, the largest USB-C plug, and the panel's screw
posts. The enclosure reads them; the board's generator and the panel will
too, so they cannot drift apart.

* A 3D-printed enclosure: a tray with four bosses for the board's screws, a
  cut-out for the USB-C plug, and vents by the sensor.
* Closed by the front panel, which screws to four posts in the tray's
  corners. The tray is wider than the board so the posts keep clear of it.
* `pcb_fit_test`: the board's holes land on the bosses, and nothing of it
  touches the walls. `interference_test`: no two parts overlap.
  `cad_check_test`: the walls are thick enough to print.

## The front panel (hdlf_rules_brep, hdlf_rules_cam)

* A 2 mm aluminium plate that closes the tray: four holes for its screws,
  a hole over the LED, and an engraved name.
* Its G-code, from FreeCAD's CAM for a GRBL router, checked against the
  machine by `gcode_check_test`. No machine runs it before a person checks
  it.

## The manual

The user manual of the hdlf_rules_* modules is written here, in LaTeX with
the IEEEtran class, and built by Bazel with a pinned TeX distribution, like
every other output. Its figures and listings come from this design's
builds: renders, reports, G-code and BUILD files, not mock-ups.
