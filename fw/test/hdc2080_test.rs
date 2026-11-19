// SPDX-License-Identifier: Apache-2.0
//! The HDC2080 crate on the host: the conversions against the datasheet's
//! formulas (SNAS678C Equations 1 to 3) computed in floating point, the
//! line format, and the driver against a fake I2C bus that records every
//! operation in order and answers from a script.
use embedded_hal_async::i2c::{ErrorKind, ErrorType, I2c, Operation};
use hdc2080::{
    centi_celsius, deci_percent, line, reg, Error, Failure, Hdc2080, Raw, ADDRESS, BOARD_VDD_MV, DRDY_TIMEOUT_MS,
    I2C_TIMEOUT_MS, POWER_UP_US,
};

// The conversions.

/// Equation 2, exactly, in hundredths of a degree, as a fraction p / q:
/// raw / 2^16 * 16500 - 4050 + 8 * (mV - 1800) / 1000, the correction only
/// above 1800 mV (Equation 1 at or below).
fn eq2(raw: u16, vdd_mv: u16) -> (i128, i128) {
    let q: i128 = 65_536 * 1_000;
    let corr = if vdd_mv > 1_800 { 8 * (vdd_mv as i128 - 1_800) * 65_536 } else { 0 };
    (raw as i128 * 16_500 * 1_000 - 4_050 * q + corr, q)
}

/// p / q rounded to the nearest integer, halves away from zero, exactly.
fn round_away(p: i128, q: i128) -> i128 {
    let m = (p.abs() * 2 + q) / (2 * q);
    if p < 0 { -m } else { m }
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
    // u16's ends: nothing overflows. 0.08 * (65.535 - 1.8) = 5.0988 °C.
    assert_eq!(centi_celsius(0, 0), -4_050);
    assert_eq!(centi_celsius(u16::MAX, u16::MAX), 12_450 + 510);
}

#[test]
fn temperature_halves_round_away_from_zero() {
    // raw 8192 is 165/8 = 20.625 °C above -40.5: -19.875 °C, a half
    // hundredth, so -19.88, away from zero. raw 57344 is 144.375 - 40.5 =
    // 103.875 °C, so 103.88.
    assert_eq!(centi_celsius(8_192, 1_800), -1_988);
    assert_eq!(centi_celsius(57_344, 1_800), 10_388);
    assert_eq!(centi_celsius(24_576, 1_800), 2_138); // 21.375
    assert_eq!(centi_celsius(40_960, 1_800), 6_263); // 62.625
}

#[test]
fn temperature_is_equation_2_rounded_once() {
    // Every raw value, at supplies from 1.62 V to 3.6 V, against Equation 2
    // computed exactly as a fraction. 2362 and 2363 mV straddle where the
    // correction, rounded alone, would change.
    for vdd_mv in [1_620u16, 1_800, 1_801, 2_362, 2_363, 2_500, 3_300, 3_600] {
        for raw in 0..=u16::MAX {
            let (p, q) = eq2(raw, vdd_mv);
            assert_eq!(centi_celsius(raw, vdd_mv) as i128, round_away(p, q), "raw {} at {} mV", raw, vdd_mv);
        }
    }
}

#[test]
fn humidity_is_equation_3_rounded() {
    assert_eq!(deci_percent(0), 0);
    // 0xFFFF is 99.998... %, rounded to 100.0.
    assert_eq!(deci_percent(0xFFFF), 1_000);
    assert_eq!(deci_percent(0x8000), 500);
    // A half tenth: raw 4096 is 6.25 %, rounded up to 6.3.
    assert_eq!(deci_percent(4_096), 63);
    for raw in 0..=u16::MAX {
        assert_eq!(deci_percent(raw) as i128, round_away(raw as i128 * 1_000, 65_536), "raw {}", raw);
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

/// The line, as format! writes it.
fn expected(c: i32, h: u32) -> String {
    let sign = if c < 0 { "-" } else { "" };
    let a = c.unsigned_abs();
    format!("t={}{}.{:02} rh={}.{}", sign, a / 100, a % 100, h / 10, h % 10)
}

#[test]
fn the_line_for_every_sensor_reading() {
    // Every temperature the board's sensor gives, and every humidity, each
    // with the other at an end: as format! writes it, and 17 bytes at most.
    for raw in 0..=u16::MAX {
        let c = centi_celsius(raw, BOARD_VDD_MV);
        let h = deci_percent(raw);
        for (c, h) in [(c, 0), (c, 1_000), (-4_038, h), (12_462, h)] {
            let s = text(c, h);
            assert_eq!(s, expected(c, h));
            assert!(s.len() <= 17, "{}", s);
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
    /// The transaction, counted from 0, that never completes.
    hang_at: Option<usize>,
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
        if self.hang_at == Some(n) {
            core::future::pending::<()>().await;
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
    let mut s = failing(0);
    assert_eq!(run(s.enable_drdy_pin()), e);
    assert_eq!(traffic(s), vec![], "a second write after the first failed");
    let mut s = failing(1);
    assert_eq!(run(s.enable_drdy_pin()), e);
    assert_eq!(traffic(s), vec![write(reg::INTERRUPT_ENABLE, 0x80)]);
}

#[test]
fn another_address() {
    // ADDR to VDD (Table 8-1): every write and read goes there.
    let answers = vec![vec![0x49, 0x54, 0xD0, 0x07], vec![0x80], vec![0, 0, 0, 0]];
    let mut s = Hdc2080::new(FakeBus { answers, ..Default::default() }, 0x41);
    run(async {
        s.trigger().await.unwrap();
        s.check_id().await.unwrap();
        s.data_ready().await.unwrap();
        s.read().await.unwrap();
    });
    let t = traffic(s);
    assert_eq!(t.len(), 4);
    assert!(t.iter().all(|(a, _)| *a == 0x41), "{:?}", t);
}

// start() and measure(): the firmware's use of the sensor, with a fake
// delay and a fake DRDY pin.

/// A delay that completes at once and records each wait, in microseconds.
#[derive(Default)]
struct FakeDelay {
    waits: Vec<u32>,
}

impl embedded_hal_async::delay::DelayNs for FakeDelay {
    async fn delay_ns(&mut self, ns: u32) {
        self.waits.push(ns / 1_000);
    }
    async fn delay_us(&mut self, us: u32) {
        self.waits.push(us);
    }
    async fn delay_ms(&mut self, ms: u32) {
        self.waits.push(ms * 1_000);
    }
}

/// A DRDY pin that is high at once, never rises, or fails.
#[derive(Clone, Copy, PartialEq)]
enum Drdy {
    Rises,
    Never,
    Fails,
}

#[derive(Debug)]
struct PinError;

impl embedded_hal::digital::Error for PinError {
    fn kind(&self) -> embedded_hal::digital::ErrorKind {
        embedded_hal::digital::ErrorKind::Other
    }
}

impl embedded_hal::digital::ErrorType for Drdy {
    type Error = PinError;
}

impl embedded_hal_async::digital::Wait for Drdy {
    async fn wait_for_high(&mut self) -> Result<(), PinError> {
        match self {
            Drdy::Rises => Ok(()),
            Drdy::Never => core::future::pending().await,
            Drdy::Fails => Err(PinError),
        }
    }
    async fn wait_for_low(&mut self) -> Result<(), PinError> {
        unimplemented!()
    }
    async fn wait_for_rising_edge(&mut self) -> Result<(), PinError> {
        unimplemented!()
    }
    async fn wait_for_falling_edge(&mut self) -> Result<(), PinError> {
        unimplemented!()
    }
    async fn wait_for_any_edge(&mut self) -> Result<(), PinError> {
        unimplemented!()
    }
}

const ID: [u8; 4] = [0x49, 0x54, 0xD0, 0x07];

#[test]
fn start_checks_resets_waits_and_routes_drdy() {
    let mut s = sensor(vec![ID.to_vec()]);
    let mut d = FakeDelay::default();
    assert_eq!(run(s.start(&mut d)), Ok(()));
    assert_eq!(
        traffic(s),
        vec![
            write_read(0xFC, 4),
            write(reg::RESET_DRDY_INT_CONF, 0x80),
            write(reg::INTERRUPT_ENABLE, 0x80),
            write(reg::RESET_DRDY_INT_CONF, 0x06),
        ]
    );
    // The 3 ms after the reset is among the waits; the rest are timeouts
    // that lost the race.
    assert!(d.waits.contains(&POWER_UP_US), "{:?}", d.waits);
}

#[test]
fn start_fails_on_another_part_and_stops() {
    let mut s = sensor(vec![vec![0, 0, 0, 0]]);
    assert_eq!(run(s.start(&mut FakeDelay::default())), Err(Failure::WrongId));
    assert_eq!(traffic(s), vec![write_read(0xFC, 4)]);
}

#[test]
fn measure_gives_the_framed_line() {
    let t = ((23.41 - 0.12 + 40.5) / 165.0 * 65536.0f64).round() as u16;
    let h = (0.452 * 65536.0f64).round() as u16;
    let data: Vec<u8> = t.to_le_bytes().into_iter().chain(h.to_le_bytes()).collect();
    let mut s = sensor(vec![vec![0x80], data]);
    let out = run(s.measure(&mut Drdy::Rises, &mut FakeDelay::default(), BOARD_VDD_MV)).unwrap();
    assert_eq!(out.as_slice(), b"t=23.41 rh=45.2\r\n");
    assert_eq!(
        traffic(s),
        vec![write(reg::MEASUREMENT_CONFIGURATION, 0x01), write_read(0x04, 1), write_read(0x00, 4)]
    );
}

#[test]
fn measure_times_out_without_drdy() {
    let mut s = sensor(vec![]);
    let mut d = FakeDelay::default();
    assert_eq!(run(s.measure(&mut Drdy::Never, &mut d, BOARD_VDD_MV)), Err(Failure::Timeout));
    // Triggered, then waited DRDY_TIMEOUT_MS for the pin, and read nothing.
    assert_eq!(traffic(s), vec![write(reg::MEASUREMENT_CONFIGURATION, 0x01)]);
    assert!(d.waits.contains(&(DRDY_TIMEOUT_MS * 1_000)), "{:?}", d.waits);
}

#[test]
fn measure_fails_when_drdy_status_is_clear() {
    let mut s = sensor(vec![vec![0x00]]);
    assert_eq!(run(s.measure(&mut Drdy::Rises, &mut FakeDelay::default(), BOARD_VDD_MV)), Err(Failure::NotReady));
    assert_eq!(traffic(s), vec![write(reg::MEASUREMENT_CONFIGURATION, 0x01), write_read(0x04, 1)]);
}

#[test]
fn measure_fails_when_the_pin_does() {
    let mut s = sensor(vec![]);
    assert_eq!(run(s.measure(&mut Drdy::Fails, &mut FakeDelay::default(), BOARD_VDD_MV)), Err(Failure::Pin));
}

#[test]
fn a_hung_bus_times_out_at_every_call() {
    // measure(): trigger, data_ready and read each hang in turn.
    for (n, answers) in [(0usize, vec![]), (1, vec![]), (2, vec![vec![0x80]])] {
        let mut s = Hdc2080::new(FakeBus { answers, hang_at: Some(n), ..Default::default() }, ADDRESS);
        let mut d = FakeDelay::default();
        assert_eq!(run(s.measure(&mut Drdy::Rises, &mut d, BOARD_VDD_MV)), Err(Failure::Timeout), "hang at {}", n);
        assert!(d.waits.contains(&(I2C_TIMEOUT_MS * 1_000)), "{:?}", d.waits);
    }
    // start(): check_id, reset and both writes of enable_drdy_pin.
    for n in 0..4usize {
        let answers = if n == 0 { vec![] } else { vec![ID.to_vec()] };
        let mut s = Hdc2080::new(FakeBus { answers, hang_at: Some(n), ..Default::default() }, ADDRESS);
        assert_eq!(run(s.start(&mut FakeDelay::default())), Err(Failure::Timeout), "hang at {}", n);
    }
}

#[test]
fn bus_errors_are_failures() {
    let mut s = failing(0);
    assert_eq!(run(s.measure(&mut Drdy::Rises, &mut FakeDelay::default(), BOARD_VDD_MV)), Err(Failure::Bus));
    let mut s = failing(0);
    assert_eq!(run(s.start(&mut FakeDelay::default())), Err(Failure::Bus));
}
