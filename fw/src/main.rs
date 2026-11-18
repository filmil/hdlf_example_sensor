// SPDX-License-Identifier: Apache-2.0
//! The sensor's firmware (issue #14, step 4): a USB CDC serial device (VID
//! 0x1209, PID 0x0001, pid.codes' test pair) that reads the HDC2080 once a
//! second and prints "t=23.41 rh=45.2". The LED blinks on each reading and
//! stays on after a sensor error, until a reading works again.
//!
//! Clocks: HSI48 is both the system clock and the USB clock, trimmed by the
//! CRS from the host's USB start-of-frame, so the board needs no crystal.
#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_stm32::exti::ExtiInput;
use embassy_stm32::gpio::{Level, Output, Pull, Speed};
use embassy_stm32::i2c::{self, I2c};
use embassy_stm32::mode::Async;
use embassy_stm32::peripherals;
use embassy_stm32::rcc::{mux, Hsi48Config, Sysclk};
use embassy_stm32::time::Hertz;
use embassy_stm32::usb::{self, Driver};
use embassy_stm32::{bind_interrupts, dma, exti, interrupt, Config};
use embassy_sync::blocking_mutex::raw::ThreadModeRawMutex;
use embassy_sync::channel::Channel;
use embassy_time::{with_timeout, Duration, Ticker, Timer};
use embassy_usb::class::cdc_acm::{CdcAcmClass, State};
use embassy_usb::UsbDevice;
use hdc2080::{centi_celsius, deci_percent, line, Hdc2080, ADDRESS, BOARD_VDD_MV, POWER_UP_US};
use panic_halt as _;
use static_cell::StaticCell;

// The pins below are the ones the board's netlist gives (//fw:pins): a
// change to the board that moves one stops this build.
const _: () = {
    assert!(pins::LED.port == 'A' && pins::LED.number == 4);
    assert!(pins::DRDY.port == 'A' && pins::DRDY.number == 0);
    assert!(pins::I2C_SCL.pin.port == 'F' && pins::I2C_SCL.pin.number == 1);
    assert!(pins::I2C_SDA.pin.port == 'F' && pins::I2C_SDA.pin.number == 0);
    assert!(pins::USB_DM.port == 'A' && pins::USB_DM.number == 11);
    assert!(pins::USB_DP.port == 'A' && pins::USB_DP.number == 12);
    assert!(pins::REMAP_PA11_PA12);
};

bind_interrupts!(struct Irqs {
    USB => usb::InterruptHandler<peripherals::USB>;
    I2C1 => i2c::EventInterruptHandler<peripherals::I2C1>, i2c::ErrorInterruptHandler<peripherals::I2C1>;
    DMA1_CHANNEL2_3 => dma::InterruptHandler<peripherals::DMA1_CH2>, dma::InterruptHandler<peripherals::DMA1_CH3>;
    EXTI0_1 => exti::InterruptHandler<interrupt::typelevel::EXTI0_1>;
});

/// A line as the host sees it: the reading and "\r\n".
type Line = heapless::Vec<u8, 34>;

/// From the sensor task to the USB task. One slot: a reading the host has
/// not taken by the next one is dropped, never queued.
static LINES: Channel<ThreadModeRawMutex, Line, 1> = Channel::new();

type UsbDriver = Driver<'static, peripherals::USB>;

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let mut config = Config::default();
    config.rcc.hsi48 = Some(Hsi48Config { sync_from_usb: true });
    config.rcc.sys = Sysclk::HSI48;
    config.rcc.mux.usbsw = mux::Usbsw::HSI48;
    let p = embassy_stm32::init(config);

    // USB is on pins 17 and 18 as PA11 and PA12 only after this remap
    // (SYSCFG_CFGR1; pins::REMAP_PA11_PA12).
    stm32_metapac::RCC.apb2enr().modify(|w| w.set_syscfgen(true));
    stm32_metapac::SYSCFG.cfgr1().modify(|w| w.set_pa11_pa12_rmp(true));

    let led = Output::new(p.PA4, Level::Low, Speed::Low);
    let drdy = ExtiInput::new(p.PA0, p.EXTI0, Pull::Down, Irqs);
    let mut i2c_config = i2c::Config::default();
    i2c_config.frequency = Hertz::khz(100);
    let i2c = I2c::new(p.I2C1, p.PF1, p.PF0, p.DMA1_CH2, p.DMA1_CH3, Irqs, i2c_config);

    let driver = Driver::new(p.USB, Irqs, p.PA12, p.PA11);
    let mut usb_config = embassy_usb::Config::new(0x1209, 0x0001);
    usb_config.manufacturer = Some("hdlfactory");
    usb_config.product = Some("hdlf_example_sensor");
    usb_config.max_power = 100;
    usb_config.max_packet_size_0 = 64;

    static CONFIG_DESC: StaticCell<[u8; 128]> = StaticCell::new();
    static BOS_DESC: StaticCell<[u8; 16]> = StaticCell::new();
    static CONTROL_BUF: StaticCell<[u8; 64]> = StaticCell::new();
    static STATE: StaticCell<State> = StaticCell::new();
    let mut builder = embassy_usb::Builder::new(
        driver,
        usb_config,
        CONFIG_DESC.init([0; 128]),
        BOS_DESC.init([0; 16]),
        &mut [],
        CONTROL_BUF.init([0; 64]),
    );
    let class = CdcAcmClass::new(&mut builder, STATE.init(State::new()), 64);
    let usb = builder.build();

    spawner.spawn(usb_task(usb).unwrap());
    spawner.spawn(serial_task(class).unwrap());
    spawner.spawn(sensor_task(Hdc2080::new(i2c, ADDRESS), drdy, led).unwrap());
}

#[embassy_executor::task]
async fn usb_task(mut usb: UsbDevice<'static, UsbDriver>) -> ! {
    usb.run().await
}

/// Sends each line to the host while a terminal is open.
#[embassy_executor::task]
async fn serial_task(mut class: CdcAcmClass<'static, UsbDriver>) -> ! {
    loop {
        class.wait_connection().await;
        loop {
            let line = LINES.receive().await;
            if class.write_packet(&line).await.is_err() {
                break;
            }
        }
    }
}

type Sensor = Hdc2080<I2c<'static, Async, i2c::Master>>;

/// The sensor's error, whatever went wrong.
struct Failed;

/// Checks the part, resets it and routes data-ready to PA0.
async fn start(sensor: &mut Sensor) -> Result<(), Failed> {
    sensor.check_id().await.map_err(|_| Failed)?;
    sensor.reset().await.map_err(|_| Failed)?;
    Timer::after_micros(POWER_UP_US as u64).await;
    sensor.enable_drdy_pin().await.map_err(|_| Failed)
}

/// One measurement, as the line the host gets. DRDY rises when it is done;
/// the typical time is 1.3 ms (MEASUREMENT_TYPICAL_US), and 100 ms without
/// it is an error. Reading DRDY_STATUS lowers the pin again.
async fn measure(sensor: &mut Sensor, drdy: &mut ExtiInput<'static, Async>) -> Result<Line, Failed> {
    sensor.trigger().await.map_err(|_| Failed)?;
    with_timeout(Duration::from_millis(100), drdy.wait_for_high()).await.map_err(|_| Failed)?;
    if !sensor.data_ready().await.map_err(|_| Failed)? {
        return Err(Failed);
    }
    let raw = sensor.read().await.map_err(|_| Failed)?;
    let mut out = Line::new();
    let text = line(centi_celsius(raw.temperature, BOARD_VDD_MV), deci_percent(raw.humidity));
    // 17 bytes at most, and 2 more, in 34.
    let _ = out.extend_from_slice(&text);
    let _ = out.extend_from_slice(b"\r\n");
    Ok(out)
}

#[embassy_executor::task]
async fn sensor_task(mut sensor: Sensor, mut drdy: ExtiInput<'static, Async>, mut led: Output<'static>) -> ! {
    Timer::after_micros(POWER_UP_US as u64).await;
    let mut started = start(&mut sensor).await.is_ok();
    let mut ticker = Ticker::every(Duration::from_secs(1));
    loop {
        ticker.next().await;
        if !started {
            started = start(&mut sensor).await.is_ok();
        }
        match if started { measure(&mut sensor, &mut drdy).await } else { Err(Failed) } {
            Ok(line) => {
                // try_send: a reading the host has not taken is dropped.
                let _ = LINES.try_send(line);
                led.set_high();
                Timer::after_millis(50).await;
                led.set_low();
            }
            Err(Failed) => {
                // On until a reading works; the next tick starts over.
                led.set_high();
                started = false;
            }
        }
    }
}
