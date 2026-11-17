// SPDX-License-Identifier: Apache-2.0
//! Reads the firmware's ELF (32-bit, little-endian, as rustc writes for
//! thumbv6m-none-eabi): its sections and loadable segments, the raw image
//! a DFU flash writes, and how much flash and RAM it uses. The standard
//! library only, so it adds no crate.

/// A section: its name, address, size, flags and type.
#[derive(Debug, Clone)]
pub struct Section {
    pub name: String,
    pub addr: u32,
    pub size: u32,
    pub flags: u32,
    pub kind: u32,
}

/// A loadable segment: where its bytes are in the file and in flash.
#[derive(Debug, Clone)]
pub struct Segment {
    pub offset: u32,
    pub paddr: u32,
    pub filesz: u32,
}

/// The parts of an ELF file this crate reads.
#[derive(Debug)]
pub struct Elf {
    pub sections: Vec<Section>,
    pub segments: Vec<Segment>,
}

const PT_LOAD: u32 = 1;
const SHF_ALLOC: u32 = 2;

fn u16_at(d: &[u8], o: usize) -> Result<u16, String> {
    d.get(o..o + 2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .ok_or_else(|| format!("the file ends before byte {}", o + 2))
}

fn u32_at(d: &[u8], o: usize) -> Result<u32, String> {
    d.get(o..o + 4)
        .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .ok_or_else(|| format!("the file ends before byte {}", o + 4))
}

/// Parses a 32-bit little-endian ELF file.
pub fn parse(d: &[u8]) -> Result<Elf, String> {
    if d.len() < 52 || &d[0..4] != b"\x7fELF" {
        return Err("not an ELF file".into());
    }
    if d[4] != 1 || d[5] != 1 {
        return Err("not a 32-bit little-endian ELF file".into());
    }
    let phoff = u32_at(d, 28)? as usize;
    let shoff = u32_at(d, 32)? as usize;
    let phentsize = u16_at(d, 42)? as usize;
    let phnum = u16_at(d, 44)? as usize;
    let shentsize = u16_at(d, 46)? as usize;
    let shnum = u16_at(d, 48)? as usize;
    let shstrndx = u16_at(d, 50)? as usize;

    let mut segments = Vec::new();
    for i in 0..phnum {
        let o = phoff + i * phentsize;
        if u32_at(d, o)? == PT_LOAD {
            segments.push(Segment {
                offset: u32_at(d, o + 4)?,
                paddr: u32_at(d, o + 12)?,
                filesz: u32_at(d, o + 16)?,
            });
        }
    }
    // The section name table.
    let str_hdr = shoff + shstrndx * shentsize;
    let str_off = u32_at(d, str_hdr + 16)? as usize;
    let mut sections = Vec::new();
    for i in 0..shnum {
        let o = shoff + i * shentsize;
        let name_off = str_off + u32_at(d, o)? as usize;
        let end = d[name_off..]
            .iter()
            .position(|&b| b == 0)
            .ok_or("a section name with no end")?;
        sections.push(Section {
            name: String::from_utf8_lossy(&d[name_off..name_off + end]).into_owned(),
            kind: u32_at(d, o + 4)?,
            flags: u32_at(d, o + 8)?,
            addr: u32_at(d, o + 12)?,
            size: u32_at(d, o + 20)?,
        });
    }
    Ok(Elf { sections, segments })
}

/// The raw image a flash writes: the loadable segments' bytes at their
/// load addresses, from the lowest, gaps filled with 0xFF (erased flash).
/// Returns the image and its start address.
pub fn image(d: &[u8], elf: &Elf) -> Result<(Vec<u8>, u32), String> {
    let mut segs: Vec<&Segment> = elf.segments.iter().filter(|s| s.filesz > 0).collect();
    segs.sort_by_key(|s| s.paddr);
    let first = segs.first().ok_or("no loadable segment with bytes")?;
    let start = first.paddr;
    let end = segs.iter().map(|s| s.paddr + s.filesz).max().unwrap();
    let mut out = vec![0xFFu8; (end - start) as usize];
    for s in segs {
        let from = s.offset as usize;
        let bytes = d
            .get(from..from + s.filesz as usize)
            .ok_or("a segment past the end of the file")?;
        let at = (s.paddr - start) as usize;
        out[at..at + bytes.len()].copy_from_slice(bytes);
    }
    Ok((out, start))
}

/// Flash and RAM use, in bytes.
#[derive(Debug, PartialEq)]
pub struct Usage {
    pub flash: u32,
    pub ram: u32,
}

/// The memory a chip has: flash from `flash_start`, RAM from `ram_start`.
pub struct Memory {
    pub flash_start: u32,
    pub flash_size: u32,
    pub ram_start: u32,
    pub ram_size: u32,
}

/// The STM32F042F6: 32 KB of flash, 6 KB of RAM (memory.x).
pub const STM32F042F6: Memory = Memory {
    flash_start: 0x0800_0000,
    flash_size: 32 * 1024,
    ram_start: 0x2000_0000,
    ram_size: 6 * 1024,
};

/// What the firmware uses: flash is every loadable byte (the code, the
/// constants and .data's initial values); RAM is every allocated section
/// in RAM (.data, .bss and the like). The stack is what RAM is left.
pub fn usage(elf: &Elf, mem: &Memory) -> Usage {
    let flash = elf.segments.iter().map(|s| s.filesz).sum();
    let ram = elf
        .sections
        .iter()
        .filter(|s| s.flags & SHF_ALLOC != 0)
        .filter(|s| s.addr >= mem.ram_start && s.addr < mem.ram_start + mem.ram_size)
        .map(|s| s.size)
        .sum();
    Usage { flash, ram }
}

/// Checks a usage against a memory: an error naming what is over.
pub fn check(u: &Usage, mem: &Memory) -> Result<String, String> {
    let line = format!(
        "flash {} of {} bytes ({:.1} %), RAM {} of {} bytes ({:.1} %)",
        u.flash,
        mem.flash_size,
        100.0 * u.flash as f64 / mem.flash_size as f64,
        u.ram,
        mem.ram_size,
        100.0 * u.ram as f64 / mem.ram_size as f64
    );
    if u.flash > mem.flash_size || u.ram > mem.ram_size {
        return Err(format!("over budget: {}", line));
    }
    Ok(line)
}
