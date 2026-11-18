// SPDX-License-Identifier: Apache-2.0
//! The sensor's firmware (issue #14). For now, only the toolchain's proof:
//! a Cortex-M0 binary that starts and sleeps.
#![no_std]
#![no_main]

use cortex_m_rt::entry;
// The chip's support crate: its peripheral access crate brings the
// interrupt vector table (device.x) that cortex-m-rt's link.x includes.
use embassy_stm32 as _;
use panic_halt as _;
// Every approved crate (issue #14) is linked, so the toolchain PR shows
// each one builds for the Cortex-M0; later steps use them.
use embassy_executor as _;
use embassy_futures as _;
use embassy_sync as _;
use embassy_time as _;
use embassy_usb as _;
use embedded_hal as _;
use embedded_hal_async as _;
use heapless as _;
// The pin map from the board's netlist (//fw:pins); step 4 uses it.
use pins as _;
// The sensor's driver (//fw:hdc2080); step 4 uses it.
use hdc2080 as _;
use static_cell as _;

#[entry]
fn main() -> ! {
    loop {
        cortex_m::asm::wfi();
    }
}
