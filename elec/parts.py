# SPDX-License-Identifier: Apache-2.0
"""The sensor board's parts: each a real, orderable part (issue #5).

Every part has its KiCad 9.0.9 symbol and footprint, whose 3D model is in
KiCad's 9.0.9 libraries, and its LCSC number, MPN, maker and datasheet.
The numbers were checked on JLCPCB's and LCSC's pages on 2026-11-01. A
datasheet URL is the maker's where it was read there (TI, GCT), else
LCSC's copy, as LCSC's own page links it. The datasheet facts the circuit
uses are cited where circuit.py uses them.

`fit` is False for a part that the board has pads for but the assembly
service does not place; `bom` is False for a board feature that is no
part at all (a solder jumper).
"""

_R0603 = "Resistor_SMD:R_0603_1608Metric"
_C0603 = "Capacitor_SMD:C_0603_1608Metric"

# Passives, all JLCPCB Basic parts.
_R5K1 = {"LCSC": "C23186", "MPN": "0603WAF5101T5E", "Manufacturer": "UNI-ROYAL",
         "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/0a975aaa49b7c97f38a963127be4a823.pdf?productCode=C23186"}
_R10K = {"LCSC": "C25804", "MPN": "0603WAF1002T5E", "Manufacturer": "UNI-ROYAL",
         "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/0a975aaa49b7c97f38a963127be4a823.pdf?productCode=C25804"}
_R1K = {"LCSC": "C21190", "MPN": "0603WAF1001T5E", "Manufacturer": "UNI-ROYAL",
        "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/0a975aaa49b7c97f38a963127be4a823.pdf?productCode=C21190"}
_C1U = {"LCSC": "C15849", "MPN": "CL10A105KB8NNNC", "Manufacturer": "Samsung Electro-Mechanics",
        "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/02336ea48ea44ca18c72517dd3cb7b47.pdf?productCode=C15849"}
_C100N = {"LCSC": "C14663", "MPN": "CC0603KRX7R9BB104", "Manufacturer": "YAGEO",
          "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/23ccee80ee542e7cf156a772bb589942.pdf?productCode=C14663"}
_C4U7 = {"LCSC": "C19666", "MPN": "CL10A475KO8NNNC", "Manufacturer": "Samsung Electro-Mechanics",
         "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/02336ea48ea44ca18c72517dd3cb7b47.pdf?productCode=C19666"}
_C10N = {"LCSC": "C57112", "MPN": "0603B103K500NT", "Manufacturer": "FH",
         "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/09fe2daf22580a99fa7fea93ccb20fb7.pdf?productCode=C57112"}


def _part(ref, lib, name, value, footprint, fields, fit=True, bom=True):
    return {"ref": ref, "lib": lib, "name": name, "value": value, "footprint": footprint,
            "fields": fields, "fit": fit, "bom": bom}


PARTS = [
    _part("J1", "Connector", "USB_C_Receptacle_USB2.0_16P", "USB4105-GF-A",
          "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
          {"LCSC": "C3020560", "MPN": "USB4105-GF-A", "Manufacturer": "GCT",
           "Datasheet": "https://gct.co/files/drawings/usb4105.pdf"}),
    _part("U4", "Power_Protection", "USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
          {"LCSC": "C7519", "MPN": "USBLC6-2SC6", "Manufacturer": "STMicroelectronics",
           "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/0d3a2ab954b34651a0695e7ccf534db0.pdf?productCode=C7519"}),
    _part("U2", "Regulator_Linear", "XC6206PxxxMR", "XC6206P332MR", "Package_TO_SOT_SMD:SOT-23-3",
          {"LCSC": "C5446", "MPN": "XC6206P332MR-G", "Manufacturer": "Torex",
           "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/221c990eb3a74b8a8233f22168ce0d59.pdf?productCode=C5446"}),
    _part("U1", "MCU_ST_STM32F0", "STM32F042F6Px", "STM32F042F6P6", "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
          {"LCSC": "C81000", "MPN": "STM32F042F6P6", "Manufacturer": "STMicroelectronics",
           "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/b700980ea5be40b58a63bcb79793ce70.pdf?productCode=C81000"}),
    _part("U3", "Sensor_Humidity", "HDC2080", "HDC2080", "Sensor_Humidity:Texas_S-PWSON-N6-HDC2080",
          {"LCSC": "C918141", "MPN": "HDC2080DMBR", "Manufacturer": "Texas Instruments",
           "Datasheet": "https://www.ti.com/lit/ds/symlink/hdc2080.pdf"}),
    _part("D1", "Device", "LED", "Red", "LED_SMD:LED_0603_1608Metric",
          {"LCSC": "C2286", "MPN": "KT-0603R", "Manufacturer": "Hubei KENTO Elec",
           "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/011ec3e8cb1e825f6961d29bc4db4c7a.pdf?productCode=C2286"}),
    _part("J2", "Connector_Generic", "Conn_01x04", "SWD", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
          {"LCSC": "C2691448", "MPN": "PZ254V-11-04P", "Manufacturer": "XFCN",
           "Datasheet": "https://datasheet.lcsc.com/datasheet/pdf/3b85a1cdf6ed945f2e278f00c1e42442.pdf?productCode=C2691448"},
          fit = False),
    _part("JP1", "Jumper", "SolderJumper_2_Open", "BOOT0", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
          {}, bom = False),
    _part("R1", "Device", "R", "5.1k", _R0603, _R5K1),
    _part("R2", "Device", "R", "5.1k", _R0603, _R5K1),
    _part("R3", "Device", "R", "10k", _R0603, _R10K),
    _part("R4", "Device", "R", "10k", _R0603, _R10K),
    _part("R5", "Device", "R", "10k", _R0603, _R10K),
    _part("R6", "Device", "R", "1k", _R0603, _R1K),
    _part("C1", "Device", "C", "1u", _C0603, _C1U),
    _part("C2", "Device", "C", "1u", _C0603, _C1U),
    _part("C3", "Device", "C", "100n", _C0603, _C100N),
    _part("C4", "Device", "C", "4.7u", _C0603, _C4U7),
    _part("C5", "Device", "C", "10n", _C0603, _C10N),
    _part("C6", "Device", "C", "1u", _C0603, _C1U),
    _part("C7", "Device", "C", "100n", _C0603, _C100N),
    _part("C8", "Device", "C", "100n", _C0603, _C100N),
]
