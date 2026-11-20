// SPDX-License-Identifier: Apache-2.0
//! The firmware fits the STM32F042F6: 32 KB of flash, and 6 KB of RAM with
//! at least 1 KB left for the stack. The margin goes to the test log
//! (--nocapture). The known-bad case: the same firmware on a chip one byte
//! too small must fail, and on one just big enough, pass. fw.bin is the
//! ELF's image.
//!
//! Two more checks keep the margin visible before it is gone:
//! - The use is recorded here, exactly. A change that grows or shrinks
//!   the firmware fails until it updates RECORDED, so its diff shows by
//!   how much. The build is reproducible (fw_determinism_test), so the
//!   numbers do not drift on their own.
//! - Headroom: flash at most 90 % of the chip, and RAM leaving at least
//!   2 KB for the stack. The last 10 % (about 3.2 KB) is room for a fix
//!   without first having to cut a feature; at 100 % even a one-line fix
//!   needs a cut. 2 KB is twice the hard minimum: the stack's depth is not
//!   measured, only bounded below, so the slack covers what an estimate
//!   would miss (interrupt frames over the executor's deepest poll).

/// The use when it was last recorded, in bytes.
const RECORDED: elf::Usage = elf::Usage { flash: 24112, ram: 2228 };

/// Flash at most 90 % of the chip.
const FLASH_HEADROOM_PERCENT: u64 = 90;

/// RAM must leave the stack at least this much.
const STACK_HEADROOM: u64 = 2 * 1024;

fn read(var: &str) -> Vec<u8> {
    let path = std::env::var(var).unwrap_or_else(|_| panic!("{}", var));
    std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {}", path, e))
}

fn firmware() -> (Vec<u8>, elf::Elf) {
    let data = read("FW_ELF");
    let parsed = elf::parse(&data).expect("parse");
    (data, parsed)
}

fn chip(flash: u64, ram: u64) -> elf::Memory {
    elf::Memory {
        flash_size: flash as u32,
        ram_size: ram as u32,
        ..elf::STM32F042F6
    }
}

#[test]
fn fits_the_chip() {
    let (d, e) = firmware();
    let u = elf::usage(&d, &e, &elf::STM32F042F6).expect("usage");
    match elf::check(&u, &elf::STM32F042F6) {
        Ok(line) => println!("budget: {}", line),
        Err(e) => panic!("{}", e),
    }
    assert!(u.flash > 0, "no flash used");
}

#[test]
fn the_use_is_the_recorded_one() {
    let (d, e) = firmware();
    let u = elf::usage(&d, &e, &elf::STM32F042F6).expect("usage");
    let delta = |now: u64, then: u64| now as i64 - then as i64;
    assert_eq!(
        u,
        RECORDED,
        "the firmware's size changed: flash {:+} bytes, RAM {:+} bytes. Record it: \
         RECORDED = elf::Usage {{ flash: {}, ram: {} }} in fw/test/budget_test.rs",
        delta(u.flash, RECORDED.flash),
        delta(u.ram, RECORDED.ram),
        u.flash,
        u.ram,
    );
}

#[test]
fn leaves_headroom() {
    let (d, e) = firmware();
    let m = &elf::STM32F042F6;
    let u = elf::usage(&d, &e, m).expect("usage");
    let flash_max = m.flash_size as u64 * FLASH_HEADROOM_PERCENT / 100;
    assert!(u.flash <= flash_max, "flash {} bytes, over {} % of {} ({} bytes)", u.flash, FLASH_HEADROOM_PERCENT, m.flash_size, flash_max);
    let stack = (m.ram_size as u64).saturating_sub(u.ram);
    assert!(stack >= STACK_HEADROOM, "RAM {} bytes leaves {} for the stack, under {}", u.ram, stack, STACK_HEADROOM);
    println!("headroom: flash {} bytes under {} %, stack {} bytes over {}", flash_max - u.flash, FLASH_HEADROOM_PERCENT, stack - STACK_HEADROOM, STACK_HEADROOM);
}

#[test]
fn a_chip_one_byte_too_small_fails() {
    let (d, e) = firmware();
    let u = elf::usage(&d, &e, &elf::STM32F042F6).expect("usage");
    let stack = elf::STM32F042F6.stack_min as u64;
    let just = chip(u.flash, u.ram + stack);
    assert!(elf::check(&elf::usage(&d, &e, &just).unwrap(), &just).is_ok(), "a chip just big enough failed: {:?}", u);
    let flash_short = chip(u.flash - 1, u.ram + stack);
    assert!(elf::check(&elf::usage(&d, &e, &flash_short).unwrap(), &flash_short).is_err(), "flash one byte short passed: {:?}", u);
    let ram_short = chip(u.flash, u.ram + stack - 1);
    assert!(elf::check(&elf::usage(&d, &e, &ram_short).unwrap(), &ram_short).is_err(), "RAM one byte short passed: {:?}", u);
}

#[test]
fn the_vector_table_is_sound() {
    let (d, e) = firmware();
    let m = &elf::STM32F042F6;
    let img = elf::image(&d, &e, m).expect("image");
    let word = |i: usize| u32::from_le_bytes([img[4 * i], img[4 * i + 1], img[4 * i + 2], img[4 * i + 3]]);
    // cortex-m-rt starts the stack at the top of RAM, 8-byte aligned.
    let sp = word(0);
    assert_eq!(sp, m.ram_start + m.ram_size, "initial stack pointer {:#x}", sp);
    assert_eq!(sp % 8, 0);
    // The reset vector points into the image, with the Thumb bit.
    let reset = word(1);
    assert_eq!(reset & 1, 1, "reset vector {:#x} lacks the Thumb bit", reset);
    let at = (reset & !1) as u64;
    assert!(at >= m.flash_start as u64 && at < m.flash_start as u64 + img.len() as u64, "reset vector {:#x} is outside the image", reset);
}

#[test]
fn fw_bin_is_the_image() {
    let (d, e) = firmware();
    let img = elf::image(&d, &e, &elf::STM32F042F6).expect("image");
    assert_eq!(read("FW_BIN"), img, "fw.bin is not the ELF's image");
}
