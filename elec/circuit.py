# SPDX-License-Identifier: Apache-2.0
"""The sensor board's circuit, in SKiDL (issue #5).

A USB 2.0 device powered by its USB-C receptacle: a 3.3 V regulator, an
STM32F042 microcontroller with crystal-less USB, an HDC2080 temperature
and humidity sensor on I2C, a status LED, and the parts each needs. The
parts are in parts.py; each comment below cites the datasheet page that
the connection follows.
"""

import builtins

from skidl import ERC, Net, Part, erc_logger

from parts import PARTS

# Each part, by reference. A part's tag is its reference, so that its link
# to its footprint on the board stays put when parts are added.
p = {}
for spec in PARTS:
    # Every part on the bill of materials is orderable as it stands.
    if spec["bom"]:
        missing = [k for k in ("LCSC", "MPN", "Manufacturer", "Datasheet") if not spec["fields"].get(k, "").strip()]
        if missing:
            raise ValueError("%s lacks %s" % (spec["ref"], ", ".join(missing)))
    part = Part(spec["lib"], spec["name"], ref=spec["ref"], tag=spec["ref"],
                value=spec["value"], footprint=spec["footprint"])
    for k, v in spec["fields"].items():
        if k == "Datasheet":
            # The symbol's own Datasheet field, replaced, not doubled.
            part.datasheet = v
        else:
            part.fields[k] = v
    # The board reads these: an unfitted part is DNP; a board feature that
    # is no part stays off the bill of materials.
    if not spec["fit"]:
        part.fields["DNP"] = "DNP"
    if not spec["bom"]:
        part.fields["Exclude from BOM"] = "yes"
    p[spec["ref"]] = part

# SKiDL's no-connect net, of the circuit the netlist is made from (the
# runner gives each script a fresh one).
# SKiDL has no import for it: its runner replaces builtins.default_circuit
# for each script, so this reads the one in use.
_nc = builtins.default_circuit.NC

vbus = Net("VBUS")
v3 = Net("+3V3")
gnd = Net("GND")
dp = Net("USB_DP")
dm = Net("USB_DM")
sda = Net("I2C_SDA")
scl = Net("I2C_SCL")

# The USB-C receptacle (GCT USB4105 drawing, rev B4): both rows' VBUS, GND,
# D+ and D- pins, so the plug fits either way up; the shell to GND. SBU1
# and SBU2 carry nothing in USB 2.0. D+ and D- leave the receptacle on
# USB_DP_C and USB_DM_C, to the ESD part below.
j1 = p["J1"]
vbus += j1["A4"], j1["A9"], j1["B4"], j1["B9"]
gnd += j1["A1"], j1["A12"], j1["B1"], j1["B12"], j1["S1"]
dp_c, dm_c = Net("USB_DP_C"), Net("USB_DM_C")
dp_c += j1["A6"], j1["B6"]
dm_c += j1["A7"], j1["B7"]
j1["A8", "B8"] += _nc

# CC1 and CC2 each to GND through Rd = 5.1 kOhm, so that a USB-C source
# gives VBUS (USB Type-C specification 1.3, table 4-21; "Both CC1 and CC2
# pins shall be independently terminated to ground through Rd").
cc1, cc2 = Net("CC1"), Net("CC2")
cc1 += j1["A5"], p["R1"][1]
cc2 += j1["B5"], p["R2"][1]
gnd += p["R1"][2], p["R2"][2]

# ESD protection on D+ and D- (USBLC6-2SC6, Doc ID 11265 p1): I/O1 on
# pins 1 and 6, I/O2 on pins 3 and 4, VBUS on 5, GND on 2. Each pair is
# one conductor inside, a flow-through: the receptacle's side (USB_DM_C,
# USB_DP_C) on pins 1 and 3, the microcontroller's on 6 and 4, as two
# nets each, so the board routes the lines through the part, not past it.
# The two channels are alike; D- takes I/O1 and D+ I/O2, so that on the
# board D- stays above D+ from the receptacle to the microcontroller.
u4 = p["U4"]
dm_c += u4[1]
dm += u4[6]
dp_c += u4[3]
dp += u4[4]
vbus += u4[5]
gnd += u4[2]

# The 3.3 V regulator (XC6206, ETR0305 p1 and p2): VIN pin 3, VOUT 2, VSS
# 1; 1 uF ceramic in and out.
u2 = p["U2"]
vbus += u2[3], p["C1"][1]
v3 += u2[2], p["C2"][1]
gnd += u2[1], p["C1"][2], p["C2"][2]

# The microcontroller (STM32F042F6P6, DocID025832 Rev 4: pins in Fig. 9
# p32 and Table 13 p33 to 36; supply scheme in Fig. 13 p44).
u1 = p["U1"]
# VDD with 100 nF and 4.7 uF; VDDA with 10 nF and 1 uF; VSS.
v3 += u1["VDD"], p["C3"][1], p["C4"][1]
v3 += u1["VDDA"], p["C5"][1], p["C6"][1]
gnd += u1["VSSA"], p["C3"][2], p["C4"][2], p["C5"][2], p["C6"][2]
# NRST with 100 nF to GND (Fig. 25 p79).
nrst = Net("NRST")
nrst += u1["NRST"], p["C7"][1]
gnd += p["C7"][2]
# USB on pins 17 (PA11, USB_DM) and 18 (PA12, USB_DP), once firmware
# remaps them (Table 13, note 1 p32); no series resistors, and the D+
# pull-up is inside (p90, note 3).
dm += u1["PA9/PA11"]
dp += u1["PA10/PA12"]
# BOOT0 (pin 1, PB8-BOOT0) low through 10 kOhm, so the part starts from
# flash; JP1, a solder jumper, pulls it high for the USB DFU bootloader
# (§3.3 p13).
boot0 = Net("BOOT0")
boot0 += u1["PB8"], p["R5"][1], p["JP1"][1]
gnd += p["R5"][2]
v3 += p["JP1"][2]
# I2C1: SDA on PF0 (pin 2), SCL on PF1 (pin 3) (Table 13 p33).
sda += u1["PF0"]
scl += u1["PF1"]
# SWD on PA13 (pin 19, SWDIO) and PA14 (pin 20, SWCLK), to J2, the
# 4-pin header the spec asks for. NRST is not on it: a part whose firmware
# turns SWD off is recovered over USB DFU, by closing JP1.
swdio, swclk = Net("SWDIO"), Net("SWCLK")
swdio += u1["PA13"]
swclk += u1["PA14"]
j2 = p["J2"]
v3 += j2[1]
swdio += j2[2]
swclk += j2[3]
gnd += j2[4]
# The status LED on PA4 (pin 10), lit when it drives high: 1 kOhm gives
# about 1 mA at the LED's 1.8 to 2.4 V (KT-0603R datasheet p3).
led = Net("LED")
led += u1["PA4"], p["R6"][1]
led_a = Net("LED_A")
led_a += p["R6"][2], p["D1"]["A"]
gnd += p["D1"]["K"]
# The sensor's data-ready line to PA0 (pin 6).
drdy = Net("DRDY")
drdy += u1["PA0"]

# The sensor (HDC2080, SNAS678C: pins p4; address table 8-1 p16; supply
# §10 p32): VDD with 100 nF; ADDR to GND for address 0x40; SDA and SCL
# pulled up to VDD by 10 kOhm (p4: they "require a pullup resistor").
u3 = p["U3"]
v3 += u3["VDD"], p["C8"][1]
gnd += u3["GND"], u3["ADDR"], p["C8"][2]
sda += u3["SDA"], p["R3"][1]
scl += u3["SCL"], p["R4"][1]
v3 += p["R3"][2], p["R4"][2]
drdy += u3["DRDY"]

# The microcontroller's other pins are free.
for pin in ["PA1", "PA2", "PA3", "PA5", "PA6", "PA7", "PB1"]:
    u1[pin] += _nc
# The sensor's exposed pad: soldered to a floating pad, "but the board pad
# should NOT be connected to GND" (SNAS678C §11.2 p33; soldered, p40 note
# 3). KiCad's symbol makes it a no-connect, and the board leaves it on no
# net.
u3["EP"] += _nc

# SKiDL's electrical rule check; any error or warning fails the build.
ERC()
_problems = erc_logger.error.count + erc_logger.bare_error.count + erc_logger.warning.count + erc_logger.bare_warning.count
if _problems:
    raise SystemExit("ERC: %d error(s) and warning(s); see above" % _problems)
