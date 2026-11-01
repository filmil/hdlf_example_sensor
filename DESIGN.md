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
(crystal-less USB), an XC6206P332MR-G regulator, an HDC2080 sensor at I²C
address 0x40, a GCT USB4105 receptacle, a USBLC6-2SC6 for ESD, and 0603
passives and LED. `elec/circuit.py` connects them, citing the datasheet
page for each connection, and fails the build on any SKiDL ERC error or
warning, or on a part that lacks its LCSC number, MPN, maker or
datasheet. The microcontroller programs over USB (DFU) with the BOOT0
solder jumper closed, or over SWD from the 4-pin header, which the
assembly service does not fit.

## The board (hdlf_rules_kicad, hdlf_rules_fab)

* 40 × 25 mm, 2 layers, 1.6 mm thick (`mech/mechanics.bzl`).
* Four M2.5 mounting holes, one at each corner, with no copper within
  their screw heads' reach.
* The USB-C receptacle at one short edge; the sensor near the other.
* DRC with JLCPCB's rules; Gerbers, drill files, positions and the BOM;
  a STEP model with the parts' 3D models; renders of both sides.
* A JLCPCB assembly package, checked by `fab_package_test`.

### How the board is made

`pcb/gen.py` writes the placed board, `placed.kicad_pcb`, from three
sources, so that none is copied by hand:

* `//elec:netlist`: each part's footprint, value and fields, and each
  pad's net;
* `mech/mechanics.bzl`: the board's size, the holes, and where the USB-C
  receptacle, the LED and the sensor sit;
* KiCad 9.0.9's footprint libraries, placed as the library has them.

Where each part goes is a reviewed table, `pcb/placement.py`.
The placed board has no copper. Freerouting routes it
(`kicad_autoroute` of hdlf_rules_kicad), with JLCPCB's clearance from the
`fab_rules` file, into `sensor.kicad_pcb`. GND is tracks; the board has
no copper pour (zone fill) in this version. The routing report,
`sensor.routing.md` (`bazel build //pcb:routing_report`), lists each net's length on each layer, its tracks
and its vias. The USB data pair runs on the top layer without vias, D+ and D- within
1 mm of each other from the receptacle to the microcontroller
(`usb_pair_test`). Full Speed USB would take far more skew; the limit
keeps the pair a pair when the placement changes.

Nothing the router writes is trusted on its own:

* `drc_test`: KiCad's DRC with JLCPCB's 2-layer rules; an unconnected
  item is an error.
* `parity_test`: the board's nets join the pins the netlist's nets join.
  Two known-bad boards, one with a pad on no net and one with two nets
  joined, must fail it.
* `pcb_determinism_test`: the same board from two configurations.
* `bad_copper_short_drc_test`: the routed board with one more track,
  joining the sensor's SDA and GND pads, must fail the DRC with
  `shorting_items` (parity checks pads' nets, so it cannot see this).
* `usb_pair_test` (above) and `pcb_test`, the generator's unit tests.

### Fab outputs

* `//pcb:jlcpcb`: JLCPCB's ZIP (`fab_package` of hdlf_rules_fab): the
  Gerbers, the drill file, `sensor_bom.csv` and `sensor_cpl.csv`.
  `jlcpcb_test` checks it against JLCPCB's file list and columns.
* The BOM comes from the netlist, not a schematic (the circuit is SKiDL):
  `pcb/bom.py` groups alike parts, leaves out the solder jumper ("Exclude
  from BOM") and marks the SWD header DNP, which the package and the
  placement list leave out.
* `//pcb:fab_summary`: the package as a page for people: the order
  settings, the files, and the parts (`//pcb:bom_md`).
* `//pcb:step` and `//pcb:render_parts`: the board with its parts, from
  KiCad's 3D models; the enclosure fits the STEP model.
* No rotation corrections are set: KiCad 9's footprints follow IPC-7351's
  zero orientation, which JLCPCB's placement mostly shares. Check each
  part's orientation in JLCPCB's placement preview before ordering.

### The sensor

The HDC2080 measures the air, not the board, so its neighbourhood is
kept cold (TI SNAS678C, section 11, "Layout"):

* An Edge.Cuts slot between it and the LED and microcontroller, the
  board's warm parts. Its tracks reach it around the slot's ends.
* No track or via on the top layer between its two pad rows, nor on the
  bottom layer under the package: keep-out rule areas that the router
  and the DRC both honour. Its die-attach pad is soldered to a floating
  pad, not to GND, as TI asks ("The DAP may be soldered to a floating
  pad on the board, but the board pad should NOT be connected to GND",
  section 11.2, page 33).

Its footprint is KiCad's `Sensor_Humidity:Texas_S-PWSON-N6-HDC2080`,
whose pads are 0.95 mm apart. TI's package outline gives the basic pitch
as 1.0 mm (page 40, "4X 1"), and its land pattern labels the pads
"(0.95) TYP" (page 41). The footprint follows the land pattern, which
is what a board is made from; the difference is inside the package's
pad tolerance.

The USB-C receptacle is 3.31 mm tall above the board (GCT's drawing of
the USB4105, revision B4, side view); `mechanics.bzl` carries that
height for the enclosure.

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
  a hole over the LED for a light pipe, and a shallow recessed label area
  (0.3 mm). An engraved name would need a font, and build123d's text reads
  the host's fonts, which a hermetic build may not.
* Its G-code, from FreeCAD's CAM for a GRBL router, checked against the
  machine by `gcode_check_test`. No machine runs it before a person checks
  it.

## The manual

The user manual of the hdlf_rules_* modules is written here, in LaTeX with
the IEEEtran class, and built by Bazel with a pinned TeX distribution, like
every other output. Its figures and listings come from this design's
builds: renders, reports, G-code and BUILD files, not mock-ups.
