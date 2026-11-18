// SPDX-License-Identifier: Apache-2.0
//! The HDC2080 crate on the host: the conversions against the datasheet's
//! formulas (SNAS678C Equations 1 to 3) computed in floating point, the
//! line format, and the driver against a fake I2C bus that records every
//! operation in order and answers from a script.
use embedded_hal_async::i2c::{ErrorKind, ErrorType, I2c, Operation};
use hdc2080::{centi_celsius, deci_percent, line, reg, Error, Hdc2080, Raw, ADDRESS, BOARD_VDD_MV};

// The conversions.

/// Equation 2 in floating point, in hundredths of a degree; Equation 1 at
/// or below 1.8 V, where the datasheet applies no correction.
fn eq2(raw: u16, vdd_mv: u16) -> f64 {
    let v = vdd_mv as f64 / 1000.0;
    (raw as f64 / 65536.0 * 165.0 - 40.5 + if v > 1.8 { 0.08 * (v - 1.8) } else { 0.0 }) * 100.0
}

/// Rounds half away from zero, as the crate does.
fn round(x: f64) -> f64 {
    x.signum() * (x.abs() + 0.5).floor()
}

#[test]
fn temperature_edges() {
    // Equation 1: raw 0 is -40.5 °C; raw 0xFFFF is 165 * 65535/65536 - 40.5
    // = 124.497... °C.
    assert_eq!(centi_celsius(0, 1_800), -4_050);
    assert_eq!(centi_celsius(0xFFFF, 1_800), 12_450);
    // On the board, 3.3 V adds 0.08 * 1.5 = 0.12 °C.
    assert_eq!(centi_celsius(0, BOARD_VDD_MV), -4_038);
    assert_eq!(centi_celsius(0xFFFF, BOARD_VDD_MV), 12_462);
    // 25 °C at 1.8 V: (25 + 40.5) / 165 * 65536 = 26015.6...
    assert_eq!(centi_celsius(26_016, 1_800), 2_500);
    // agy's case: the two terms rounded apart gave -4009.
    assert_eq!(centi_celsius(109, 3_600), -4_008);
    // The datasheet's lowest supply is 1.62 V (§7.3): no correction.
    assert_eq!(centi_celsius(0, 1_620), -4_050);
}

#[test]
fn temperature_is_equation_2_rounded_once() {
    // Every raw value, at supplies from 1.62 V to 3.6 V, and at the ones
    // whose correction lands on a half hundredth (2362.5 mV).
    for vdd_mv in [1_620u16, 1_800, 1_801, 2_362, 2_363, 2_500, 3_300, 3_600] {
        for raw in 0..=u16::MAX {
            let want = round(eq2(raw, vdd_mv));
            let got = centi_celsius(raw, vdd_mv) as f64;
            // Equal, except where the exact value is within float noise of
            // a half and the float rounding cannot say which way.
            let exact = eq2(raw, vdd_mv);
            let near_half = ((exact.abs().fract()) - 0.5).abs() < 1e-9;
            assert!(got == want || (near_half && (got - exact).abs() <= 0.5 + 1e-9),
                "raw {} at {} mV: {} vs {} ({})", raw, vdd_mv, got, want, exact);
        }
    }
}

#[test]
fn humidity_is_equation_3_rounded() {
    assert_eq!(deci_percent(0), 0);
    // 0xFFFF is 99.998... %, rounded to 100.0.
    assert_eq!(deci_percent(0xFFFF), 1_000);
    assert_eq!(deci_percent(0x8000), 500);
    for raw in 0..=u16::MAX {
        let exact = raw as f64 / 65536.0 * 1000.0;
        assert!((deci_percent(raw) as f64 - exact).abs() <= 0.5, "raw {}", raw);
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
    assert_eq!(text(12_462, 999), "t=124.62 rh=99.9");
}

#[test]
fn the_line_for_every_sensor_reading() {
    // Every value the conversions give on the board, at both ends of the
    // other: at most 17 bytes, and it reads back as the value.
    let lo = deci_percent(0);
    let hi = deci_percent(0xFFFF);
    for raw in 0..=u16::MAX {
        let c = centi_celsius(raw, BOARD_VDD_MV);
        for h in [lo, hi] {
            let s = text(c, h);
            assert!(s.len() <= 17, "{}", s);
            let t: f64 = s[2..s.find(' ').unwrap()].parse().unwrap();
            assert!((t * 100.0 - c as f64).abs() < 0.5, "{} for {}", s, c);
        }
    }
}

#[test]
fn the_line_holds_any_input() {
    // Not readings the sensor gives, but no input is cut.
    assert_eq!(text(i32::MIN, u32::MAX), "t=-21474836.48 rh=429496729.5");
    assert_eq!(text(i32::MAX, 0), "t=21474836.47 rh=0.0");
    assert_eq!(text(-10_000_000, 1_000_000_000), "t=-100000.00 rh=100000000.0");
}

// The driver, on a fake bus.

#[derive(Debug, Clone, Copy, PartialEq)]
struct BusError;

impl embedded_hal_async::i2c::Error for BusError {
    fn kind(&self) -> ErrorKind {
        ErrorKind::Other
    }
}

/// One operation of a transaction, as the bus saw it.
#[derive(Debug, PartialEq)]
enum Op {
    Write(Vec<u8>),
    Read(usize),
}

/// A bus that records each transaction's operations in order, answers
/// reads from a script, and can fail one transaction.
#[derive(Default)]
struct FakeBus {
    seen: Vec<(u8, Vec<Op>)>,
    answers: Vec<Vec<u8>>,
    /// The transaction, counted from 0, that fails.
    fail_at: Option<usize>,
    count: usize,
}

impl ErrorType for FakeBus {
    type Error = BusError;
}

impl I2c for FakeBus {
    async fn transaction(&mut self, address: u8, ops: &mut [Operation<'_>]) -> Result<(), BusError> {
        let n = self.count;
        self.count += 1;
        if self.fail_at == Some(n) {
            return Err(BusError);
        }
        let mut seen = vec![];
        for op in ops {
            match op {
                Operation::Write(b) => seen.push(Op::Write(b.to_vec())),
                Operation::Read(buf) => {
                    assert!(!self.answers.is_empty(), "a read with no answer scripted");
                    let answer = self.answers.remove(0);
                    assert_eq!(answer.len(), buf.len(), "the script's answer has the wrong length");
                    buf.copy_from_slice(&answer);
                    seen.push(Op::Read(buf.len()));
                }
            }
        }
        self.seen.push((address, seen));
        Ok(())
    }
}

fn run<F: core::future::Future>(f: F) -> F::Output {
    embassy_futures::block_on(f)
}

fn sensor(answers: Vec<Vec<u8>>) -> Hdc2080<FakeBus> {
    Hdc2080::new(FakeBus { answers, ..Default::default() }, ADDRESS)
}

/// The bus's record, after checking every scripted answer was used.
fn traffic(s: Hdc2080<FakeBus>) -> Vec<(u8, Vec<Op>)> {
    let bus = s.release();
    assert!(bus.answers.is_empty(), "answers left unread: {:?}", bus.answers);
    bus.seen
}

/// A register read: the pointer written, then n bytes read, in one
/// transaction (a repeated start).
fn write_read(register: u8, n: usize) -> (u8, Vec<Op>) {
    (0x40, vec![Op::Write(vec![register]), Op::Read(n)])
}

/// A register write: pointer and value in one write.
fn write(register: u8, value: u8) -> (u8, Vec<Op>) {
    (0x40, vec![Op::Write(vec![register, value])])
}

#[test]
fn check_id_reads_four_bytes_from_0xfc() {
    // 0x5449 and 0x07D0, LSB first, as Table 8-6's reset values.
    let mut s = sensor(vec![vec![0x49, 0x54, 0xD0, 0x07]]);
    assert_eq!(run(s.check_id()), Ok(()));
    assert_eq!(traffic(s), vec![write_read(0xFC, 4)]);
}

#[test]
fn check_id_refuses_another_part() {
    // Another device of TI's.
    let mut s = sensor(vec![vec![0x49, 0x54, 0x50, 0x10]]);
    assert_eq!(run(s.check_id()), Err(Error::WrongId(0x5449, 0x1050)));
    assert_eq!(traffic(s), vec![write_read(0xFC, 4)]);
    // Another manufacturer's part with the HDC2080's device ID.
    let mut s = sensor(vec![vec![0x00, 0x00, 0xD0, 0x07]]);
    assert_eq!(run(s.check_id()), Err(Error::WrongId(0x0000, 0x07D0)));
    assert_eq!(traffic(s), vec![write_read(0xFC, 4)]);
}

#[test]
fn configuration_writes() {
    let mut s = sensor(vec![]);
    run(async {
        s.reset().await.unwrap();
        // The firmware waits POWER_UP_US here; the fake bus needs no wait.
        s.enable_drdy_pin().await.unwrap();
        s.trigger().await.unwrap();
    });
    assert_eq!(
        traffic(s),
        vec![
            // SOFT_RES.
            write(reg::RESET_DRDY_INT_CONF, 0x80),
            // DRDY_ENABLE, then DRDY/INT_EN with INT_POL high.
            write(reg::INTERRUPT_ENABLE, 0x80),
            write(reg::RESET_DRDY_INT_CONF, 0x06),
            // MEAS_TRIG, 14 bit, humidity and temperature.
            write(reg::MEASUREMENT_CONFIGURATION, 0x01),
        ]
    );
}

#[test]
fn data_ready_is_bit_7() {
    let mut s = sensor(vec![vec![0x80], vec![0x7F]]);
    assert_eq!(run(s.data_ready()), Ok(true));
    // Every other status bit set, DRDY_STATUS clear.
    assert_eq!(run(s.data_ready()), Ok(false));
    assert_eq!(traffic(s), vec![write_read(0x04, 1), write_read(0x04, 1)]);
}

#[test]
fn read_is_one_four_byte_read_lsb_first() {
    let mut s = sensor(vec![vec![0x34, 0x12, 0x78, 0x56]]);
    assert_eq!(run(s.read()), Ok(Raw { temperature: 0x1234, humidity: 0x5678 }));
    assert_eq!(traffic(s), vec![write_read(0x00, 4)]);
}

#[test]
fn a_reading_end_to_end() {
    // Raw values for 23.41 °C and 45.2 %RH at 3.3 V.
    let t = ((23.41 - 0.12 + 40.5) / 165.0 * 65536.0f64).round() as u16;
    let h = (0.452 * 65536.0f64).round() as u16;
    let mut s = sensor(vec![t.to_le_bytes().into_iter().chain(h.to_le_bytes()).collect()]);
    let raw = run(s.read()).unwrap();
    assert_eq!(traffic(s), vec![write_read(0x00, 4)]);
    let out = text(centi_celsius(raw.temperature, BOARD_VDD_MV), deci_percent(raw.humidity));
    assert_eq!(out, "t=23.41 rh=45.2");
}

fn failing(at: usize) -> Hdc2080<FakeBus> {
    Hdc2080::new(FakeBus { fail_at: Some(at), ..Default::default() }, ADDRESS)
}

#[test]
fn bus_errors_pass_through() {
    let e: Result<(), _> = Err(Error::I2c(BusError));
    assert_eq!(run(failing(0).read()).map(|_| ()), e);
    assert_eq!(run(failing(0).trigger()), e);
    assert_eq!(run(failing(0).check_id()), e);
    assert_eq!(run(failing(0).reset()), e);
    assert_eq!(run(failing(0).data_ready()).map(|_| ()), e);
    // enable_drdy_pin: its first write fails, or its second, after the
    // first has happened (as its doc says).
    assert_eq!(run(failing(0).enable_drdy_pin()), e);
    let mut s = failing(1);
    assert_eq!(run(s.enable_drdy_pin()), e);
    assert_eq!(traffic(s), vec![write(reg::INTERRUPT_ENABLE, 0x80)]);
}

#[test]
fn another_address() {
    let mut s = Hdc2080::new(FakeBus::default(), 0x41);
    run(s.trigger()).unwrap();
    assert_eq!(s.release().seen[0].0, 0x41);
}
