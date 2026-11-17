// SPDX-License-Identifier: Apache-2.0
//! The ELF reader on small ELF files written here, byte by byte: good ones,
//! and malformed ones, which must give an error and never a panic.

const FLASH: u32 = 0x0800_0000;
const RAM: u32 = 0x2000_0000;
const ALLOC: u32 = 2;

/// A segment: load address and bytes.
struct Seg(u32, Vec<u8>);
/// A section: name, flags, address, size.
struct Sec(&'static str, u32, u32, u32);

/// Writes an ELF32 file with these segments and sections, plus the null
/// section and the name table.
fn build(segs: &[Seg], secs: &[Sec]) -> Vec<u8> {
    let mut d = vec![0u8; 52];
    d[0..4].copy_from_slice(b"\x7fELF");
    d[4] = 1;
    d[5] = 1;
    let put32 = |d: &mut Vec<u8>, o: usize, v: u32| d[o..o + 4].copy_from_slice(&v.to_le_bytes());
    let put16 = |d: &mut Vec<u8>, o: usize, v: u16| d[o..o + 2].copy_from_slice(&v.to_le_bytes());
    // Program headers right after the ELF header, then the bytes.
    let phoff = 52;
    d.resize(phoff + 32 * segs.len(), 0);
    for (i, s) in segs.iter().enumerate() {
        let off = d.len() as u32;
        d.extend_from_slice(&s.1);
        let o = phoff + 32 * i;
        put32(&mut d, o, 1);
        put32(&mut d, o + 4, off);
        put32(&mut d, o + 12, s.0);
        put32(&mut d, o + 16, s.1.len() as u32);
    }
    // The name table.
    let mut names = vec![0u8];
    let mut at = vec![];
    for s in secs.iter().map(|s| s.0).chain([".shstrtab"]) {
        at.push(names.len() as u32);
        names.extend_from_slice(s.as_bytes());
        names.push(0);
    }
    let str_off = d.len() as u32;
    d.extend_from_slice(&names);
    // Section headers: null, the sections, the name table.
    let shoff = d.len();
    let n = secs.len() + 2;
    d.resize(shoff + 40 * n, 0);
    for (i, s) in secs.iter().enumerate() {
        let o = shoff + 40 * (i + 1);
        put32(&mut d, o, at[i]);
        put32(&mut d, o + 8, s.1);
        put32(&mut d, o + 12, s.2);
        put32(&mut d, o + 20, s.3);
    }
    let o = shoff + 40 * (n - 1);
    put32(&mut d, o, at[secs.len()]);
    put32(&mut d, o + 16, str_off);
    put32(&mut d, o + 20, names.len() as u32);
    put32(&mut d, 28, phoff as u32);
    put32(&mut d, 32, shoff as u32);
    put16(&mut d, 42, 32);
    put16(&mut d, 44, segs.len() as u16);
    put16(&mut d, 46, 40);
    put16(&mut d, 48, n as u16);
    put16(&mut d, 50, (n - 1) as u16);
    d
}

fn mem() -> &'static elf::Memory {
    &elf::STM32F042F6
}

#[test]
fn reads_sections_segments_and_usage() {
    let d = build(&[Seg(FLASH, vec![1, 2, 3, 4, 5, 6, 7, 8])], &[Sec(".text", ALLOC | 4, FLASH, 8), Sec(".bss", ALLOC | 1, RAM, 16)]);
    let e = elf::parse(&d).unwrap();
    let names: Vec<&str> = e.sections.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, vec!["", ".text", ".bss", ".shstrtab"]);
    assert_eq!(elf::image(&d, &e, mem()).unwrap(), vec![1, 2, 3, 4, 5, 6, 7, 8]);
    assert_eq!(elf::usage(&d, &e, mem()).unwrap(), elf::Usage { flash: 8, ram: 16 });
}

#[test]
fn fills_gaps_and_sorts_segments() {
    // Out of order, with a gap of 4 bytes; .data's initial values load in
    // flash after the code.
    let d = build(&[Seg(FLASH + 8, vec![9, 9]), Seg(FLASH, vec![1, 2, 3, 4])], &[]);
    let e = elf::parse(&d).unwrap();
    assert_eq!(elf::image(&d, &e, mem()).unwrap(), vec![1, 2, 3, 4, 0xFF, 0xFF, 0xFF, 0xFF, 9, 9]);
    assert_eq!(elf::usage(&d, &e, mem()).unwrap().flash, 10);
}

#[test]
fn image_starts_at_flash_even_if_the_code_does_not() {
    let d = build(&[Seg(FLASH + 4, vec![7])], &[]);
    let e = elf::parse(&d).unwrap();
    assert_eq!(elf::image(&d, &e, mem()).unwrap(), vec![0xFF, 0xFF, 0xFF, 0xFF, 7]);
}

#[test]
fn refuses_overlapping_segments() {
    let d = build(&[Seg(FLASH, vec![1, 2, 3, 4]), Seg(FLASH + 2, vec![5])], &[]);
    let e = elf::parse(&d).unwrap();
    assert!(elf::image(&d, &e, mem()).unwrap_err().contains("overlaps"));
}

#[test]
fn refuses_bytes_loaded_outside_flash() {
    // The case that would otherwise make a 384 MB image.
    let d = build(&[Seg(FLASH, vec![1]), Seg(RAM, vec![2])], &[]);
    let e = elf::parse(&d).unwrap();
    assert!(elf::image(&d, &e, mem()).unwrap_err().contains("outside flash"));
}

#[test]
fn ram_counts_padding_between_sections() {
    let d = build(&[Seg(FLASH, vec![0])], &[Sec(".data", ALLOC | 1, RAM, 4), Sec(".bss", ALLOC | 1, RAM + 64, 4)]);
    let e = elf::parse(&d).unwrap();
    assert_eq!(elf::usage(&d, &e, mem()).unwrap().ram, 68);
}

#[test]
fn a_section_past_ram_still_counts() {
    let d = build(&[Seg(FLASH, vec![0])], &[Sec(".bss", ALLOC | 1, RAM + 6 * 1024, 4)]);
    let e = elf::parse(&d).unwrap();
    let u = elf::usage(&d, &e, mem()).unwrap();
    assert_eq!(u.ram, 6 * 1024 + 4);
    assert!(elf::check(&u, mem()).is_err());
}

#[test]
fn refuses_a_section_outside_both_memories() {
    let d = build(&[Seg(FLASH, vec![0])], &[Sec(".odd", ALLOC, 0x1000_0000, 4)]);
    let e = elf::parse(&d).unwrap();
    assert!(elf::usage(&d, &e, mem()).unwrap_err().contains("neither in flash nor in RAM"));
}

#[test]
fn ignores_sections_that_are_not_allocated() {
    let d = build(&[Seg(FLASH, vec![0])], &[Sec(".debug_info", 0, 0, 999)]);
    let e = elf::parse(&d).unwrap();
    assert_eq!(elf::usage(&d, &e, mem()).unwrap(), elf::Usage { flash: 1, ram: 0 });
}

#[test]
fn reads_a_file_with_no_sections() {
    let mut d = build(&[Seg(FLASH, vec![1, 2])], &[]);
    d[48..50].copy_from_slice(&0u16.to_le_bytes()); // shnum = 0
    let e = elf::parse(&d).unwrap();
    assert!(e.sections.is_empty());
    assert_eq!(elf::image(&d, &e, mem()).unwrap(), vec![1, 2]);
}

#[test]
fn malformed_files_are_errors() {
    let good = build(&[Seg(FLASH, vec![1, 2])], &[Sec(".text", ALLOC, FLASH, 2)]);
    assert!(elf::parse(&good).is_ok());
    let cases: Vec<(&str, Box<dyn Fn(&mut Vec<u8>)>)> = vec![
        ("not ELF", Box::new(|d| d[0] = 0)),
        ("64-bit", Box::new(|d| d[4] = 2)),
        ("big-endian", Box::new(|d| d[5] = 2)),
        ("cut short", Box::new(|d| d.truncate(60))),
        ("program header too small", Box::new(|d| d[42..44].copy_from_slice(&8u16.to_le_bytes()))),
        ("section header too small", Box::new(|d| d[46..48].copy_from_slice(&8u16.to_le_bytes()))),
        ("name table index too big", Box::new(|d| d[50..52].copy_from_slice(&9u16.to_le_bytes()))),
        ("section table past the end", Box::new(|d| d[32..36].copy_from_slice(&0xFFFF_FFF0u32.to_le_bytes()))),
        ("name past the name table", Box::new(|d| {
            let shoff = u32::from_le_bytes([d[32], d[33], d[34], d[35]]) as usize;
            d[shoff + 40..shoff + 44].copy_from_slice(&0xFFFFu32.to_le_bytes());
        })),
    ];
    for (what, f) in cases {
        let mut d = good.clone();
        f(&mut d);
        assert!(elf::parse(&d).is_err(), "{}: parsed", what);
    }
    // A segment whose bytes are past the end of the file.
    let mut d = good.clone();
    d[52 + 4..52 + 8].copy_from_slice(&0xFFFF_FF00u32.to_le_bytes());
    let e = elf::parse(&d).unwrap();
    assert!(elf::image(&d, &e, mem()).is_err());
}

#[test]
fn checks_the_budget_at_its_edges() {
    let m = mem();
    let fits = elf::Usage { flash: m.flash_size as u64, ram: (m.ram_size - m.stack_min) as u64 };
    assert!(elf::check(&fits, m).is_ok());
    assert!(elf::check(&elf::Usage { flash: fits.flash + 1, ram: fits.ram }, m).is_err());
    assert!(elf::check(&elf::Usage { flash: fits.flash, ram: fits.ram + 1 }, m).is_err());
}
