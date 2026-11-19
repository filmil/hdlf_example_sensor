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
use embassy_sync::signal::Signal;
use embassy_time::{with_timeout, Delay, Duration, Ticker, Timer};
use embassy_usb::class::cdc_acm::{CdcAcmClass, State};
use embassy_usb::UsbDevice;
use hdc2080::{Framed, Hdc2080, ADDRESS, BOARD_VDD_MV};
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

/// The latest reading, from the sensor task to the serial task. A new
/// reading replaces one the serial task has not taken: the host gets the
/// latest, never a queue of old ones.
static LATEST: Signal<ThreadModeRawMutex, Framed> = Signal::new();

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
    // embassy has no API for it, so the firmware writes the registers.
    // SYSCFG's registers need its clock on: reading RCC back makes the
    // enable complete before SYSCFG is written.
    stm32_metapac::RCC.apb2enr().modify(|w| w.set_syscfgen(true));
    let _ = stm32_metapac::RCC.apb2enr().read();
    stm32_metapac::SYSCFG.cfgr1().modify(|w| w.set_pa11_pa12_rmp(true));

    // These pins must be the ones the const block at the top asserts from
    // //fw:pins: change both together.
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

/// Sends the latest reading to the host while a terminal has the port open
/// (DTR set). A write the host does not take within 100 ms is dropped, so
/// a host that stops reading never stalls the device; on a new connection,
/// any reading taken before it is discarded.
#[embassy_executor::task]
async fn serial_task(mut class: CdcAcmClass<'static, UsbDriver>) -> ! {
    loop {
        class.wait_connection().await;
        LATEST.reset();
        loop {
            let line = LATEST.wait().await;
            if !class.dtr() {
                continue;
            }
            match with_timeout(Duration::from_millis(100), class.write_packet(&line)).await {
                Ok(Ok(())) | Err(_) => {}
                // The device was unplugged or reset: wait for the next
                // connection.
                Ok(Err(_)) => break,
            }
        }
    }
}

type Sensor = Hdc2080<I2c<'static, Async, i2c::Master>>;

/// Every second: a reading, framed, to the serial task, and a 50 ms blink.
/// On any failure (hdc2080::Failure: a bus error, a timeout of an I2C call
/// or of DRDY, another part) the LED stays on, and the next tick starts
/// the sensor over: ID check, soft reset, 3 ms, the DRDY pin.
#[embassy_executor::task]
async fn sensor_task(mut sensor: Sensor, mut drdy: ExtiInput<'static, Async>, mut led: Output<'static>) -> ! {
    let mut delay = Delay;
    // The sensor's power-up time (hdc2080::POWER_UP_US) passes in the first
    // second of the ticker.
    let mut started = false;
    let mut ticker = Ticker::every(Duration::from_secs(1));
    loop {
        ticker.next().await;
        if !started {
            started = sensor.start(&mut delay).await.is_ok();
        }
        let reading = if started {
            sensor.measure(&mut drdy, &mut delay, BOARD_VDD_MV).await.ok()
        } else {
            None
        };
        match reading {
            Some(line) => {
                LATEST.signal(line);
                led.set_high();
                Timer::after_millis(50).await;
                led.set_low();
            }
            None => {
                led.set_high();
                started = false;
            }
        }
    }
}
