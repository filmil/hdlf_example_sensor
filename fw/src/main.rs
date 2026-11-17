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

#[entry]
fn main() -> ! {
    loop {
        cortex_m::asm::wfi();
    }
}
