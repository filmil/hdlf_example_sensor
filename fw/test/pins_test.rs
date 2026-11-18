// SPDX-License-Identifier: Apache-2.0
//! The pin map says what elec/circuit.py wires, for the pins the firmware
//! will configure: a regression check on the generated crate.
use pins::{AfPin, Pin};

#[test]
fn usb_is_on_the_remapped_pair() {
    assert_eq!(pins::USB_DM, Pin { port: 'A', number: 11 });
    assert_eq!(pins::USB_DP, Pin { port: 'A', number: 12 });
    assert!(pins::REMAP_PA11_PA12);
}

#[test]
fn i2c1_is_on_pf0_and_pf1() {
    assert_eq!(pins::I2C_SDA, AfPin { pin: Pin { port: 'F', number: 0 }, af: 1 });
    assert_eq!(pins::I2C_SCL, AfPin { pin: Pin { port: 'F', number: 1 }, af: 1 });
}

#[test]
fn the_rest() {
    assert_eq!(pins::LED, Pin { port: 'A', number: 4 });
    assert_eq!(pins::DRDY, Pin { port: 'A', number: 0 });
    assert_eq!(pins::BOOT0, Pin { port: 'B', number: 8 });
}
