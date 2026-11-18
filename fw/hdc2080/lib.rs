// SPDX-License-Identifier: Apache-2.0
//! The HDC2080 humidity and temperature sensor, over I2C, and the line the
//! firmware prints for each reading (issue #14, step 3).
//!
//! Every register, bit and formula is from TI's datasheet, SNAS678C (July
//! 2021): https://www.ti.com/lit/ds/symlink/hdc2080.pdf. Section and table
//! numbers below are that revision's.
//!
//! The arithmetic is integer fixed point: the Cortex-M0 has no FPU, and
//! soft float would cost flash. Temperatures are in hundredths of a degree
//! Celsius, humidity in tenths of a percent.
#![no_std]

use embedded_hal_async::i2c::I2c;

/// The 7-bit address with ADDR tied to GND, as on the board (Table 8-1).
pub const ADDRESS: u8 = 0x40;

/// Registers (Table 8-6).
pub mod reg {
    /// TEMPERATURE LOW; then TEMPERATURE HIGH, HUMIDITY LOW and HUMIDITY
    /// HIGH. A read from here auto-increments through all four (§8.5.2),
    /// LSB first, as §8.6.2 and §8.6.4 require.
    pub const TEMPERATURE_LOW: u8 = 0x00;
    /// INTERRUPT/DRDY: bit 7 is DRDY_STATUS, cleared when read (Table 8-16).
    pub const INTERRUPT_DRDY: u8 = 0x04;
    /// Interrupt configuration: bit 7 is DRDY_ENABLE (Table 8-22).
    pub const INTERRUPT_ENABLE: u8 = 0x07;
    /// RESET&DRDY/INT CONF: bit 7 SOFT_RES, bits 6:4 AMM (000: measure on
    /// request), bit 2 DRDY/INT_EN, bit 1 INT_POL, bit 0 INT_MODE
    /// (Table 8-36).
    pub const RESET_DRDY_INT_CONF: u8 = 0x0E;
    /// MEASUREMENT CONFIGURATION: bits 7:6 TRES, 5:4 HRES (00: 14 bit),
    /// bits 2:1 MEAS_CONF (00: humidity and temperature), bit 0 MEAS_TRIG,
    /// which clears itself when the measurement completes (Table 8-38).
    pub const MEASUREMENT_CONFIGURATION: u8 = 0x0F;
    /// MANUFACTURER ID LOW; then HIGH, DEVICE ID LOW and HIGH.
    pub const MANUFACTURER_ID_LOW: u8 = 0xFC;
}

/// Manufacturer ID, 0x5449 (reset values of 0xFC and 0xFD, Table 8-6).
pub const MANUFACTURER_ID: u16 = 0x5449;
/// Device ID, 0x07D0 (reset values of 0xFE and 0xFF, Table 8-6).
pub const DEVICE_ID: u16 = 0x07D0;

/// SOFT_RES (Table 8-36).
const SOFT_RES: u8 = 1 << 7;
/// DRDY/INT_EN and INT_POL: the DRDY pin driven, active high, level
/// sensitive (Table 8-36).
const DRDY_PIN_ACTIVE_HIGH: u8 = (1 << 2) | (1 << 1);
/// DRDY_ENABLE (Table 8-22).
const DRDY_ENABLE: u8 = 1 << 7;
/// MEAS_TRIG with 14-bit humidity and temperature (Table 8-38).
const MEASURE_BOTH_14_BIT: u8 = 1 << 0;
/// DRDY_STATUS (Table 8-16).
const DRDY_STATUS: u8 = 1 << 7;

/// The longest a 14-bit humidity and temperature measurement takes, in
/// microseconds: RHCT 660 µs plus TEMPCT 610 µs (§7.5, typical values).
pub const MEASUREMENT_US: u32 = 660 + 610;
/// The longest the sensor needs after power-up, in microseconds (§8.5.2).
pub const POWER_UP_US: u32 = 3_000;

/// The board's supply, in millivolts: the XC6206P332 regulator's 3.3 V.
pub const BOARD_VDD_MV: u32 = 3_300;

/// The two raw results of one measurement.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Raw {
    pub temperature: u16,
    pub humidity: u16,
}

/// What can go wrong.
#[derive(Debug, PartialEq, Eq)]
pub enum Error<E> {
    /// The I2C bus failed.
    I2c(E),
    /// The part at the address is not an HDC2080: (manufacturer, device).
    WrongId(u16, u16),
}

impl<E> From<E> for Error<E> {
    fn from(e: E) -> Self {
        Error::I2c(e)
    }
}

/// The temperature in hundredths of a degree Celsius, from Equation 2
/// (§8.6.2): raw / 2^16 * 165 - 40.5 + TEMPPSRR * (VDD - 1.8 V), with
/// TEMPPSRR 0.08 °C/V (§7.5, typical). The correction applies above 1.8 V;
/// at or below it, this is Equation 1. Each term is rounded to the nearest
/// hundredth.
pub fn centi_celsius(raw: u16, vdd_mv: u32) -> i32 {
    let scaled = ((raw as u32 * 16_500 + (1 << 15)) >> 16) as i32;
    let psrr = if vdd_mv > 1_800 {
        // 0.08 °C/V = 8 hundredths per volt = 8 hundredths per 1000 mV.
        ((8 * (vdd_mv - 1_800) + 500) / 1_000) as i32
    } else {
        0
    };
    scaled - 4_050 + psrr
}

/// The relative humidity in tenths of a percent, from Equation 3 (§8.6.4):
/// raw / 2^16 * 100, rounded to the nearest tenth.
pub fn deci_percent(raw: u16) -> u32 {
    (raw as u32 * 1_000 + (1 << 15)) >> 16
}

/// The line the firmware prints for a reading: "t=23.41 rh=45.2", with no
/// line ending. The longest, "t=-40.50 rh=100.0", is 17 bytes.
pub fn line(centi_c: i32, deci_rh: u32) -> heapless::Vec<u8, 24> {
    let mut out = heapless::Vec::new();
    // 24 bytes hold the longest line, so no push below can fail.
    let _ = out.extend_from_slice(b"t=");
    if centi_c < 0 {
        let _ = out.push(b'-');
    }
    let c = centi_c.unsigned_abs();
    push_decimal(&mut out, c / 100);
    let _ = out.push(b'.');
    let _ = out.push(b'0' + (c / 10 % 10) as u8);
    let _ = out.push(b'0' + (c % 10) as u8);
    let _ = out.extend_from_slice(b" rh=");
    push_decimal(&mut out, deci_rh / 10);
    let _ = out.push(b'.');
    let _ = out.push(b'0' + (deci_rh % 10) as u8);
    out
}

fn push_decimal(out: &mut heapless::Vec<u8, 24>, mut n: u32) {
    let mut digits = [0u8; 10];
    let mut i = digits.len();
    loop {
        i -= 1;
        digits[i] = b'0' + (n % 10) as u8;
        n /= 10;
        if n == 0 {
            break;
        }
    }
    let _ = out.extend_from_slice(&digits[i..]);
}

/// The sensor on an I2C bus.
pub struct Hdc2080<I> {
    i2c: I,
    address: u8,
}

impl<I: I2c> Hdc2080<I> {
    pub fn new(i2c: I, address: u8) -> Self {
        Hdc2080 { i2c, address }
    }

    /// Gives the bus back.
    pub fn release(self) -> I {
        self.i2c
    }

    /// Checks that the part is an HDC2080, by its manufacturer and device
    /// IDs.
    pub async fn check_id(&mut self) -> Result<(), Error<I::Error>> {
        let mut id = [0u8; 4];
        self.i2c.write_read(self.address, &[reg::MANUFACTURER_ID_LOW], &mut id).await?;
        let manufacturer = u16::from_le_bytes([id[0], id[1]]);
        let device = u16::from_le_bytes([id[2], id[3]]);
        if (manufacturer, device) != (MANUFACTURER_ID, DEVICE_ID) {
            return Err(Error::WrongId(manufacturer, device));
        }
        Ok(())
    }

    /// Resets the registers and reloads the calibration (SOFT_RES).
    pub async fn reset(&mut self) -> Result<(), Error<I::Error>> {
        self.write(reg::RESET_DRDY_INT_CONF, SOFT_RES).await
    }

    /// Drives the DRDY pin high when a measurement completes, so the
    /// firmware can wait on PA0 instead of polling.
    pub async fn enable_drdy_pin(&mut self) -> Result<(), Error<I::Error>> {
        self.write(reg::INTERRUPT_ENABLE, DRDY_ENABLE).await?;
        self.write(reg::RESET_DRDY_INT_CONF, DRDY_PIN_ACTIVE_HIGH).await
    }

    /// Starts one 14-bit humidity and temperature measurement.
    pub async fn trigger(&mut self) -> Result<(), Error<I::Error>> {
        self.write(reg::MEASUREMENT_CONFIGURATION, MEASURE_BOTH_14_BIT).await
    }

    /// Whether a measurement has completed since the last call: reading
    /// DRDY_STATUS clears it.
    pub async fn data_ready(&mut self) -> Result<bool, Error<I::Error>> {
        let mut status = [0u8; 1];
        self.i2c.write_read(self.address, &[reg::INTERRUPT_DRDY], &mut status).await?;
        Ok(status[0] & DRDY_STATUS != 0)
    }

    /// Reads the last measurement: one read of four bytes from 0x00.
    pub async fn read(&mut self) -> Result<Raw, Error<I::Error>> {
        let mut b = [0u8; 4];
        self.i2c.write_read(self.address, &[reg::TEMPERATURE_LOW], &mut b).await?;
        Ok(Raw {
            temperature: u16::from_le_bytes([b[0], b[1]]),
            humidity: u16::from_le_bytes([b[2], b[3]]),
        })
    }

    async fn write(&mut self, register: u8, value: u8) -> Result<(), Error<I::Error>> {
        self.i2c.write(self.address, &[register, value]).await?;
        Ok(())
    }
}
