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

/// How long a 14-bit humidity and temperature measurement typically takes,
/// in microseconds: RHCT 660 µs plus TEMPCT 610 µs (§7.5). The datasheet
/// gives typical values only, no maximum, so the firmware waits for
/// DRDY_STATUS (or the DRDY pin) rather than for this long.
pub const MEASUREMENT_TYPICAL_US: u32 = 660 + 610;
/// The longest the sensor needs after power-up, in microseconds (§8.5.2).
/// The datasheet gives no time for a soft reset, which reloads the same
/// calibration (Table 8-36); waiting this long after `reset` too is this
/// crate's choice, not TI's.
pub const POWER_UP_US: u32 = 3_000;

/// The board's supply, in millivolts: the XC6206P332 regulator's 3.3 V.
pub const BOARD_VDD_MV: u16 = 3_300;

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
/// TEMPPSRR 0.08 °C/V (§7.5, typical). The datasheet applies the correction
/// for supplies above 1.8 V only; at or below, this is Equation 1. The
/// result is the exact value rounded once, to the nearest hundredth, halves
/// away from zero.
pub fn centi_celsius(raw: u16, vdd_mv: u16) -> i32 {
    // In units of 1 / (2^16 * 1000) of a hundredth of a degree, so every
    // term is an integer: raw * 16500 / 2^16, then -4050, then the
    // correction, 8 hundredths per volt, i.e. 8 * (mV - 1800) / 1000.
    const DEN: i64 = 65_536 * 1_000;
    let psrr = if vdd_mv > 1_800 { 8 * (vdd_mv as i64 - 1_800) * 65_536 } else { 0 };
    let num = raw as i64 * 16_500 * 1_000 - 4_050 * DEN + psrr;
    // Rounds |num| / DEN to the nearest, halves up, without a 64-bit
    // division (the Cortex-M0 has no divider): floor(x / (2^16 * 1000)) is
    // floor(floor(x / 2^16) / 1000), and x / 2^16 fits a u32.
    let x = num.unsigned_abs() + (DEN / 2) as u64;
    let q = ((x >> 16) as u32 / 1_000) as i32;
    if num < 0 { -q } else { q }
}

/// The relative humidity in tenths of a percent, from Equation 3 (§8.6.4):
/// raw / 2^16 * 100, rounded to the nearest tenth.
pub fn deci_percent(raw: u16) -> u32 {
    (raw as u32 * 1_000 + (1 << 15)) >> 16
}

/// The line the firmware prints for a reading: "t=23.41 rh=45.2", with no
/// line ending. The sensor's own range gives at most 17 bytes
/// ("t=-40.50 rh=100.0", "t=124.62 rh=100.0"); the buffer holds any
/// i32 and u32, at most 29 bytes, so no input is cut.
pub fn line(centi_c: i32, deci_rh: u32) -> heapless::Vec<u8, 32> {
    let mut out = Line::default();
    out.put(b"t=");
    if centi_c < 0 {
        out.put(b"-");
    }
    let c = centi_c.unsigned_abs();
    out.decimal(c / 100);
    out.put(&[b'.', b'0' + (c / 10 % 10) as u8, b'0' + (c % 10) as u8]);
    out.put(b" rh=");
    out.decimal(deci_rh / 10);
    out.put(&[b'.', b'0' + (deci_rh % 10) as u8]);
    out.0
}

#[derive(Default)]
struct Line(heapless::Vec<u8, 32>);

impl Line {
    fn put(&mut self, b: &[u8]) {
        // 32 bytes hold the longest line any input gives (29), so this
        // cannot fail; the_line_holds_any_input checks the longest.
        let _ = self.0.extend_from_slice(b);
    }

    fn decimal(&mut self, mut n: u32) {
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
        self.put(&digits[i..]);
    }
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

    /// Resets the registers and reloads the calibration (SOFT_RES). The
    /// caller waits `POWER_UP_US` before the next command.
    pub async fn reset(&mut self) -> Result<(), Error<I::Error>> {
        self.write(reg::RESET_DRDY_INT_CONF, SOFT_RES).await
    }

    /// Drives the DRDY pin high when a measurement completes, so the
    /// firmware can wait on PA0 instead of polling. Level sensitive
    /// (INT_MODE 0): the pin stays high until DRDY_STATUS is read, so the
    /// caller reads `data_ready` after each measurement, before the next
    /// `trigger` (§8.3).
    ///
    /// Like `trigger`, it writes whole registers: the firmware owns every
    /// bit of 0x07, 0x0E and 0x0F, and wants the heater, auto measurement
    /// and the threshold interrupts off. If the second write fails, the
    /// first has happened; the firmware's answer to any sensor error is a
    /// `reset` and a fresh start.
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

// The firmware's use of the sensor, generic over embedded-hal-async's
// traits so that the host can test it: the DRDY pin is a `Wait`, and every
// timeout comes from a `DelayNs`.

use embassy_futures::select::{select, Either};
use embedded_hal_async::delay::DelayNs;
use embedded_hal_async::digital::Wait;

/// The longest any one I2C call may take before the firmware gives up on
/// it, in milliseconds: at 100 kHz the longest call, 6 bytes, takes under
/// 1 ms. A sensor holding the bus low would otherwise hang the firmware.
pub const I2C_TIMEOUT_MS: u32 = 50;
/// The longest the firmware waits for DRDY after a trigger, in
/// milliseconds: about 80 times the typical 1.27 ms.
pub const DRDY_TIMEOUT_MS: u32 = 100;

/// A line as the host gets it: the reading and "\r\n". `line` gives at
/// most 32 bytes, so 34 always hold it.
pub type Framed = heapless::Vec<u8, 34>;

/// Why a reading failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    /// The bus returned an error.
    Bus,
    /// The part is not an HDC2080.
    WrongId,
    /// An I2C call, or DRDY, took longer than its timeout.
    Timeout,
    /// DRDY rose but DRDY_STATUS was clear.
    NotReady,
    /// The DRDY pin returned an error.
    Pin,
}

impl<E> From<Error<E>> for Failure {
    fn from(e: Error<E>) -> Self {
        match e {
            Error::I2c(_) => Failure::Bus,
            Error::WrongId(..) => Failure::WrongId,
        }
    }
}

/// Runs `f`, or fails with Timeout after `ms` milliseconds.
async fn timed<F: core::future::Future, D: DelayNs>(delay: &mut D, ms: u32, f: F) -> Result<F::Output, Failure> {
    match select(f, delay.delay_ms(ms)).await {
        Either::First(out) => Ok(out),
        Either::Second(()) => Err(Failure::Timeout),
    }
}

impl<I: I2c> Hdc2080<I> {
    /// Brings the sensor up: checks its ID, soft-resets it, waits
    /// `POWER_UP_US`, and routes data-ready to the DRDY pin. The firmware
    /// calls it at start and after any failure.
    pub async fn start<D: DelayNs>(&mut self, delay: &mut D) -> Result<(), Failure> {
        timed(delay, I2C_TIMEOUT_MS, self.check_id()).await??;
        timed(delay, I2C_TIMEOUT_MS, self.reset()).await??;
        delay.delay_us(POWER_UP_US).await;
        timed(delay, I2C_TIMEOUT_MS, self.enable_drdy_pin()).await??;
        Ok(())
    }

    /// One reading, framed for the host: trigger, wait for DRDY (at most
    /// `DRDY_TIMEOUT_MS`), read DRDY_STATUS (which lowers the pin), read the
    /// results, convert at `vdd_mv`, and format.
    pub async fn measure<P: Wait, D: DelayNs>(&mut self, drdy: &mut P, delay: &mut D, vdd_mv: u16) -> Result<Framed, Failure> {
        timed(delay, I2C_TIMEOUT_MS, self.trigger()).await??;
        timed(delay, DRDY_TIMEOUT_MS, drdy.wait_for_high()).await?.map_err(|_| Failure::Pin)?;
        if !timed(delay, I2C_TIMEOUT_MS, self.data_ready()).await?? {
            return Err(Failure::NotReady);
        }
        let raw = timed(delay, I2C_TIMEOUT_MS, self.read()).await??;
        let text = line(centi_celsius(raw.temperature, vdd_mv), deci_percent(raw.humidity));
        let mut out = Framed::new();
        // 32 + 2 bytes fit 34 (Framed's doc), so neither can fail.
        out.extend_from_slice(&text).map_err(|_| Failure::Bus)?;
        out.extend_from_slice(b"\r\n").map_err(|_| Failure::Bus)?;
        Ok(out)
    }
}
