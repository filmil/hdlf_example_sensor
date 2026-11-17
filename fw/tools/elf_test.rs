// SPDX-License-Identifier: Apache-2.0
//! The reader on a small ELF written here, byte by byte.

/// An ELF32 file: one PT_LOAD of 8 bytes at 0x08000000, sections .text
/// (flash) and .bss (RAM, 16 bytes).
fn tiny() -> Vec<u8> {
    let mut d = vec![0u8; 0x200];
    d[0..4].copy_from_slice(b"\x7fELF");
    d[4] = 1; // 32-bit
    d[5] = 1; // little-endian
    let put32 = |d: &mut Vec<u8>, o: usize, v: u32| d[o..o + 4].copy_from_slice(&v.to_le_bytes());
    let put16 = |d: &mut Vec<u8>, o: usize, v: u16| d[o..o + 2].copy_from_slice(&v.to_le_bytes());
    put32(&mut d, 28, 0x40); // phoff
    put32(&mut d, 32, 0x100); // shoff
    put16(&mut d, 42, 32); // phentsize
    put16(&mut d, 44, 1); // phnum
    put16(&mut d, 46, 40); // shentsize
    put16(&mut d, 48, 4); // shnum: null, .text, .bss, .shstrtab
    put16(&mut d, 50, 3); // shstrndx
    // PT_LOAD: offset 0x80, paddr 0x08000000, filesz 8.
    put32(&mut d, 0x40, 1);
    put32(&mut d, 0x44, 0x80);
    put32(&mut d, 0x4c, 0x0800_0000);
    put32(&mut d, 0x50, 8);
    d[0x80..0x88].copy_from_slice(&[1, 2, 3, 4, 5, 6, 7, 8]);
    // Names at 0x1c0: "\0.text\0.bss\0.shstrtab\0".
    let names = b"\0.text\0.bss\0.shstrtab\0";
    d[0x1c0..0x1c0 + names.len()].copy_from_slice(names);
    let sh = |d: &mut Vec<u8>, i: usize, name: u32, kind: u32, flags: u32, addr: u32, off: u32, size: u32| {
        let o = 0x100 + i * 40;
        d[o..o + 4].copy_from_slice(&name.to_le_bytes());
        d[o + 4..o + 8].copy_from_slice(&kind.to_le_bytes());
        d[o + 8..o + 12].copy_from_slice(&flags.to_le_bytes());
        d[o + 12..o + 16].copy_from_slice(&addr.to_le_bytes());
        d[o + 16..o + 20].copy_from_slice(&off.to_le_bytes());
        d[o + 20..o + 24].copy_from_slice(&size.to_le_bytes());
    };
    sh(&mut d, 1, 1, 1, 6, 0x0800_0000, 0x80, 8); // .text: PROGBITS, ALLOC|EXEC
    sh(&mut d, 2, 7, 8, 3, 0x2000_0000, 0, 16); // .bss: NOBITS, ALLOC|WRITE
    sh(&mut d, 3, 12, 3, 0, 0, 0x1c0, names.len() as u32); // .shstrtab
    d
}

#[test]
fn parses_sections_and_segments() {
    let d = tiny();
    let e = elf::parse(&d).unwrap();
    let names: Vec<&str> = e.sections.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, vec!["", ".text", ".bss", ".shstrtab"]);
    assert_eq!(e.segments.len(), 1);
    assert_eq!(elf::usage(&e, &elf::STM32F042F6), elf::Usage { flash: 8, ram: 16 });
    let (img, start) = elf::image(&d, &e).unwrap();
    assert_eq!((img, start), (vec![1, 2, 3, 4, 5, 6, 7, 8], 0x0800_0000));
}

#[test]
fn refuses_what_is_not_elf32_le() {
    assert!(elf::parse(b"not an elf file at all, not at all, not at all, nope").is_err());
    let mut d = tiny();
    d[4] = 2; // 64-bit
    assert!(elf::parse(&d).is_err());
    assert!(elf::parse(&d[..20]).is_err());
}

#[test]
fn checks_the_budget() {
    let tight = elf::Memory { flash_start: 0x0800_0000, flash_size: 4, ram_start: 0x2000_0000, ram_size: 6 * 1024 };
    let u = elf::Usage { flash: 8, ram: 16 };
    assert!(elf::check(&u, &tight).is_err());
    assert!(elf::check(&u, &elf::STM32F042F6).unwrap().starts_with("flash 8 of 32768 bytes"));
}
