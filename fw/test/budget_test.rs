// SPDX-License-Identifier: Apache-2.0
//! The firmware fits the STM32F042F6: 32 KB of flash, and 6 KB of RAM with
//! at least 1 KB left for the stack. The margin goes to the test log. The
//! known-bad case: the same firmware on a chip one byte too small must
//! fail, and on one just big enough, pass. fw.bin is the ELF's image.

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
