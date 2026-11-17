// SPDX-License-Identifier: Apache-2.0
//! The firmware fits the STM32F042F6: 32 KB of flash, 6 KB of RAM. The
//! margin goes to the test log. The known-bad case: the same firmware on a
//! chip one byte too small must fail, and on one just big enough, pass.

fn firmware() -> (Vec<u8>, elf::Elf) {
    let path = std::env::var("FW_ELF").expect("FW_ELF");
    let data = std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {}", path, e));
    let parsed = elf::parse(&data).expect("parse");
    (data, parsed)
}

#[test]
fn fits_the_chip() {
    let (_, e) = firmware();
    let u = elf::usage(&e, &elf::STM32F042F6);
    match elf::check(&u, &elf::STM32F042F6) {
        Ok(line) => println!("budget: {}", line),
        Err(e) => panic!("{}", e),
    }
    assert!(u.flash > 0, "no flash used: the ELF has no loadable bytes");
}

#[test]
fn a_chip_one_byte_too_small_fails() {
    let (_, e) = firmware();
    let u = elf::usage(&e, &elf::STM32F042F6);
    let chip = |flash, ram| elf::Memory { flash_start: 0x0800_0000, flash_size: flash, ram_start: 0x2000_0000, ram_size: ram };
    assert!(elf::check(&u, &chip(u.flash, u.ram)).is_ok(), "a chip just big enough failed: {:?}", u);
    assert!(elf::check(&u, &chip(u.flash - 1, u.ram)).is_err(), "flash one byte short passed: {:?}", u);
    if u.ram > 0 {
        assert!(elf::check(&u, &chip(u.flash, u.ram - 1)).is_err(), "RAM one byte short passed: {:?}", u);
    }
}

#[test]
fn image_starts_at_flash() {
    let (data, e) = firmware();
    let (img, start) = elf::image(&data, &e).expect("image");
    assert_eq!(start, 0x0800_0000);
    // The vector table: the initial stack pointer is in RAM, the reset
    // vector in flash, with the Thumb bit.
    let sp = u32::from_le_bytes([img[0], img[1], img[2], img[3]]);
    let reset = u32::from_le_bytes([img[4], img[5], img[6], img[7]]);
    assert!((0x2000_0000..=0x2000_0000 + 6 * 1024).contains(&sp), "stack pointer {:#x}", sp);
    assert!((0x0800_0000..0x0800_0000 + 32 * 1024).contains(&(reset & !1)) && reset & 1 == 1, "reset vector {:#x}", reset);
}
