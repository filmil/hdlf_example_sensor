// SPDX-License-Identifier: Apache-2.0
//! The HDC2080 crate on the host: the conversions against the datasheet's
//! formulas (SNAS678C Equations 1 to 3) computed in floating point, the
//! line format, and the driver against a fake I2C bus that records every
//! transaction and answers from a script.
use embedded_hal_async::i2c::{ErrorKind, ErrorType, I2c, Operation};
use hdc2080::{centi_celsius, deci_percent, line, reg, Error, Hdc2080, Raw, ADDRESS, BOARD_VDD_MV};

// The conversions.

/// Equation 2 in floating point, in °C.
fn eq2(raw: u16, vdd_v: f64) -> f64 {
    raw as f64 / 65536.0 * 165.0 - 40.5 + if vdd_v > 1.8 { 0.08 * (vdd_v - 1.8) } else { 0.0 }
}

#[test]
fn temperature_edges() {
    // Equation 1 (no correction at 1.8 V): raw 0 is -40.5 °C, raw 0xFFFF
    // is 165 * 65535/65536 - 40.5 = 124.497... °C.
    assert_eq!(centi_celsius(0, 1_800), -4_050);
    assert_eq!(centi_celsius(0xFFFF, 1_800), 12_450);
    // On the board, 3.3 V adds 0.08 * 1.5 = 0.12 °C.
    assert_eq!(centi_celsius(0, BOARD_VDD_MV), -4_038);
    // 25 °C at 1.8 V: (25 + 40.5) / 165 * 65536 = 26015.6...
    assert_eq!(centi_celsius(26_016, 1_800), 2_500);
}

#[test]
fn temperature_matches_equation_2_everywhere() {
    for vdd_mv in [1_800u32, 3_300, 3_600] {
        for raw in (0..=u16::MAX).step_by(7).chain([u16::MAX]) {
            let want = eq2(raw, vdd_mv as f64 / 1000.0) * 100.0;
            let got = centi_celsius(raw, vdd_mv) as f64;
            // Two terms, each rounded to the nearest hundredth.
            assert!((got - want).abs() <= 1.0, "raw {} at {} mV: {} vs {}", raw, vdd_mv, got, want);
        }
    }
}

#[test]
fn humidity_edges_and_equation_3() {
    assert_eq!(deci_percent(0), 0);
    // 0xFFFF is 99.998... %, rounded to 100.0.
    assert_eq!(deci_percent(0xFFFF), 1_000);
    assert_eq!(deci_percent(0x8000), 500);
    for raw in (0..=u16::MAX).step_by(5).chain([u16::MAX]) {
        let want = raw as f64 / 65536.0 * 1000.0;
        assert!((deci_percent(raw) as f64 - want).abs() <= 0.5, "raw {}", raw);
    }
}

// The line.

fn text(centi: i32, deci: u32) -> String {
    String::from_utf8(line(centi, deci).to_vec()).unwrap()
}

#[test]
fn the_line() {
    // The plan's example (issue #14).
    assert_eq!(text(2_341, 452), "t=23.41 rh=45.2");
    assert_eq!(text(0, 0), "t=0.00 rh=0.0");
    assert_eq!(text(5, 1), "t=0.05 rh=0.1");
    assert_eq!(text(-5, 1_000), "t=-0.05 rh=100.0");
    assert_eq!(text(-4_050, 0), "t=-40.50 rh=0.0");
    assert_eq!(text(12_450, 999), "t=124.50 rh=99.9");
    // The longest the sensor can give fits the buffer.
    assert_eq!(text(-4_050, 1_000).len(), 17);
}

#[test]
fn every_reading_formats() {
    for t in [0u16, 1, 0x7FFF, 0xFFFF] {
        for h in [0u16, 1, 0x8000, 0xFFFF] {
            let s = text(centi_celsius(t, BOARD_VDD_MV), deci_percent(h));
            assert!(s.starts_with("t=") && s.contains(" rh="), "{}", s);
        }
    }
}

// The driver, on a fake bus.

#[derive(Debug, Clone, Copy, PartialEq)]
struct BusError;

impl embedded_hal_async::i2c::Error for BusError {
    fn kind(&self) -> ErrorKind {
        ErrorKind::Other
    }
}

/// One transaction: the address, the bytes written, how many were read.
#[derive(Debug, PartialEq)]
struct Seen {
    address: u8,
    wrote: Vec<u8>,
    read: usize,
}

/// A bus that records transactions and answers reads from a script.
#[derive(Default)]
struct FakeBus {
    seen: Vec<Seen>,
    answers: Vec<Vec<u8>>,
    fail: bool,
}

impl ErrorType for FakeBus {
    type Error = BusError;
}

impl I2c for FakeBus {
    async fn transaction(&mut self, address: u8, ops: &mut [Operation<'_>]) -> Result<(), BusError> {
        if self.fail {
            return Err(BusError);
        }
        let mut seen = Seen { address, wrote: vec![], read: 0 };
        for op in ops {
            match op {
                Operation::Write(b) => seen.wrote.extend_from_slice(b),
                Operation::Read(buf) => {
                    let answer = self.answers.remove(0);
                    assert_eq!(answer.len(), buf.len(), "the script's answer has the wrong length");
                    buf.copy_from_slice(&answer);
                    seen.read += buf.len();
                }
            }
        }
        self.seen.push(seen);
        Ok(())
    }
}

fn run<F: core::future::Future>(f: F) -> F::Output {
    embassy_futures::block_on(f)
}

fn sensor(answers: Vec<Vec<u8>>) -> Hdc2080<FakeBus> {
    Hdc2080::new(FakeBus { answers, ..Default::default() }, ADDRESS)
}

fn seen(address: u8, wrote: &[u8], read: usize) -> Seen {
    Seen { address, wrote: wrote.to_vec(), read }
}

#[test]
fn check_id_reads_four_bytes_from_0xfc() {
    // 0x5449 and 0x07D0, LSB first, as Table 8-6's reset values.
    let mut s = sensor(vec![vec![0x49, 0x54, 0xD0, 0x07]]);
    assert_eq!(run(s.check_id()), Ok(()));
    assert_eq!(s.release().seen, vec![seen(0x40, &[0xFC], 4)]);
}

#[test]
fn check_id_refuses_another_part() {
    let mut s = sensor(vec![vec![0x49, 0x54, 0x50, 0x10]]);
    assert_eq!(run(s.check_id()), Err(Error::WrongId(0x5449, 0x1050)));
}

#[test]
fn configuration_writes() {
    let mut s = sensor(vec![]);
    run(async {
        s.reset().await.unwrap();
        s.enable_drdy_pin().await.unwrap();
        s.trigger().await.unwrap();
    });
    assert_eq!(
        s.release().seen,
        vec![
            // SOFT_RES.
            seen(0x40, &[reg::RESET_DRDY_INT_CONF, 0x80], 0),
            // DRDY_ENABLE, then DRDY/INT_EN with INT_POL high.
            seen(0x40, &[reg::INTERRUPT_ENABLE, 0x80], 0),
            seen(0x40, &[reg::RESET_DRDY_INT_CONF, 0x06], 0),
            // MEAS_TRIG, 14 bit, humidity and temperature.
            seen(0x40, &[reg::MEASUREMENT_CONFIGURATION, 0x01], 0),
        ]
    );
}

#[test]
fn data_ready_is_bit_7() {
    let mut s = sensor(vec![vec![0x80], vec![0x7F]]);
    assert_eq!(run(s.data_ready()), Ok(true));
    // Every other status bit set, DRDY_STATUS clear.
    assert_eq!(run(s.data_ready()), Ok(false));
    assert_eq!(s.release().seen, vec![seen(0x40, &[0x04], 1), seen(0x40, &[0x04], 1)]);
}

#[test]
fn read_is_one_four_byte_read_lsb_first() {
    let mut s = sensor(vec![vec![0x34, 0x12, 0x78, 0x56]]);
    assert_eq!(run(s.read()), Ok(Raw { temperature: 0x1234, humidity: 0x5678 }));
    assert_eq!(s.release().seen, vec![seen(0x40, &[0x00], 4)]);
}

#[test]
fn a_reading_end_to_end() {
    // Raw values for about 23.4 °C and 45.2 %RH at 3.3 V.
    let t = ((23.41 - 0.12 + 40.5) / 165.0 * 65536.0) as u16;
    let h = (0.452 * 65536.0) as u16;
    let mut s = sensor(vec![t.to_le_bytes().into_iter().chain(h.to_le_bytes()).collect()]);
    let raw = run(s.read()).unwrap();
    let out = text(centi_celsius(raw.temperature, BOARD_VDD_MV), deci_percent(raw.humidity));
    assert_eq!(out, "t=23.41 rh=45.2");
}

#[test]
fn bus_errors_pass_through() {
    let mut s = Hdc2080::new(FakeBus { fail: true, ..Default::default() }, ADDRESS);
    assert_eq!(run(s.read()), Err(Error::I2c(BusError)));
    assert_eq!(run(s.trigger()), Err(Error::I2c(BusError)));
    assert_eq!(run(s.check_id()), Err(Error::I2c(BusError)));
}

#[test]
fn another_address() {
    let mut s = Hdc2080::new(FakeBus::default(), 0x41);
    run(s.trigger()).unwrap();
    assert_eq!(s.release().seen[0].address, 0x41);
}
