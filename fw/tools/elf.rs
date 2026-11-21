// SPDX-License-Identifier: Apache-2.0
//! Reads the firmware's ELF (32-bit, little-endian, as rustc writes for
//! thumbv6m-none-eabi): its sections and loadable segments, the raw image
//! a DFU flash writes, and how much flash and RAM it uses. The standard
//! library only, so it adds no crate. Every read is bounds-checked: a
//! malformed file is an error, never a panic.

/// A section: its name, address, size and flags.
#[derive(Debug, Clone)]
pub struct Section {
    pub name: String,
    pub addr: u32,
    pub size: u32,
    pub flags: u32,
}

/// A loadable segment: where its bytes are in the file, and the address
/// they load at (the LMA: for .data, its initial values in flash).
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
const EHDR_SIZE: usize = 52;
const PHDR_SIZE: usize = 32;
const SHDR_SIZE: usize = 40;

fn bytes(d: &[u8], o: usize, n: usize) -> Result<&[u8], String> {
    o.checked_add(n)
        .and_then(|end| d.get(o..end))
        .ok_or_else(|| format!("the file ends before byte {} + {}", o, n))
}

fn u16_at(d: &[u8], o: usize) -> Result<u16, String> {
    let b = bytes(d, o, 2)?;
    Ok(u16::from_le_bytes([b[0], b[1]]))
}

fn u32_at(d: &[u8], o: usize) -> Result<u32, String> {
    let b = bytes(d, o, 4)?;
    Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}

/// The offset of entry `i` of a table at `off` with entries of `size`.
fn entry(off: usize, i: usize, size: usize) -> Result<usize, String> {
    i.checked_mul(size)
        .and_then(|x| x.checked_add(off))
        .ok_or_else(|| "a header table past any file".to_string())
}

/// Parses a 32-bit little-endian ELF file.
pub fn parse(d: &[u8]) -> Result<Elf, String> {
    if d.len() < EHDR_SIZE || &d[0..4] != b"\x7fELF" {
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
    if phnum > 0 && phentsize < PHDR_SIZE {
        return Err(format!("program headers of {} bytes, want at least {}", phentsize, PHDR_SIZE));
    }
    if shnum > 0 && shentsize < SHDR_SIZE {
        return Err(format!("section headers of {} bytes, want at least {}", shentsize, SHDR_SIZE));
    }

    let mut segments = Vec::new();
    for i in 0..phnum {
        let o = entry(phoff, i, phentsize)?;
        if u32_at(d, o)? == PT_LOAD {
            segments.push(Segment {
                offset: u32_at(d, o + 4)?,
                paddr: u32_at(d, o + 12)?,
                filesz: u32_at(d, o + 16)?,
            });
        }
    }

    let mut sections = Vec::new();
    if shnum > 0 {
        if shstrndx >= shnum {
            return Err(format!("the name table is section {}, of {}", shstrndx, shnum));
        }
        let str_hdr = entry(shoff, shstrndx, shentsize)?;
        let names = bytes(d, u32_at(d, str_hdr + 16)? as usize, u32_at(d, str_hdr + 20)? as usize)?;
        for i in 0..shnum {
            let o = entry(shoff, i, shentsize)?;
            let at = u32_at(d, o)? as usize;
            let rest = names.get(at..).ok_or_else(|| format!("section {}: its name is past the name table", i))?;
            let end = rest
                .iter()
                .position(|&b| b == 0)
                .ok_or_else(|| format!("section {}: its name has no end", i))?;
            sections.push(Section {
                name: String::from_utf8_lossy(&rest[..end]).into_owned(),
                flags: u32_at(d, o + 8)?,
                addr: u32_at(d, o + 12)?,
                size: u32_at(d, o + 20)?,
            });
        }
    }
    Ok(Elf { sections, segments })
}

/// The memory a chip has, and how much RAM the stack needs at least.
pub struct Memory {
    pub flash_start: u32,
    pub flash_size: u32,
    pub ram_start: u32,
    pub ram_size: u32,
    pub stack_min: u32,
}

/// The STM32F042F6: 32 KB of flash, 6 KB of RAM (memory.x). The stack
/// grows down from the top of RAM, and gets at least 1 KB.
pub const STM32F042F6: Memory = Memory {
    flash_start: 0x0800_0000,
    flash_size: 32 * 1024,
    ram_start: 0x2000_0000,
    ram_size: 6 * 1024,
    stack_min: 1024,
};

fn end(start: u32, size: u32) -> Result<u64, String> {
    Ok(start as u64 + size as u64)
}

/// The raw image a flash writes: the loadable bytes at their load
/// addresses, from the start of flash, gaps filled with 0xFF (erased
/// flash). Every segment with bytes must load into flash, and none may
/// overlap another. The image may be bigger than the flash: check() says.
pub fn image(d: &[u8], elf: &Elf, mem: &Memory) -> Result<Vec<u8>, String> {
    let mut segs: Vec<&Segment> = elf.segments.iter().filter(|s| s.filesz > 0).collect();
    if segs.is_empty() {
        return Err("no loadable segment with bytes".into());
    }
    segs.sort_by_key(|s| s.paddr);
    let flash_end = end(mem.flash_start, mem.flash_size)?;
    let mut last = mem.flash_start as u64;
    for s in &segs {
        let e = end(s.paddr, s.filesz)?;
        if (s.paddr as u64) < mem.flash_start as u64 || s.paddr as u64 >= flash_end {
            return Err(format!("a segment of {} bytes loads at {:#010x}, outside flash", s.filesz, s.paddr));
        }
        if (s.paddr as u64) < last {
            return Err(format!("the segment at {:#010x} overlaps the one before it", s.paddr));
        }
        last = e;
    }
    let mut out = vec![0xFFu8; (last - mem.flash_start as u64) as usize];
    for s in segs {
        let src = bytes(d, s.offset as usize, s.filesz as usize).map_err(|e| format!("a segment's bytes: {}", e))?;
        let at = (s.paddr - mem.flash_start) as usize;
        out[at..at + src.len()].copy_from_slice(src);
    }
    Ok(out)
}

/// Flash and RAM use, in bytes.
#[derive(Debug, PartialEq)]
pub struct Usage {
    pub flash: u64,
    pub ram: u64,
}

/// What the firmware uses. Flash: the image's length, gaps included (it is
/// what DFU writes). RAM: from the start of RAM to the end of the last
/// allocated section there (.data, .bss and the like), padding included.
/// An allocated section neither in flash nor in RAM is an error.
pub fn usage(d: &[u8], elf: &Elf, mem: &Memory) -> Result<Usage, String> {
    let flash = image(d, elf, mem)?.len() as u64;
    let flash_end = end(mem.flash_start, mem.flash_size)?;
    let mut ram = 0u64;
    for s in elf.sections.iter().filter(|s| s.flags & SHF_ALLOC != 0 && s.size > 0) {
        let e = end(s.addr, s.size)?;
        let a = s.addr as u64;
        if a >= mem.flash_start as u64 && a < flash_end {
            continue; // counted in the image
        }
        // A section past the end of RAM still counts, so check() fails.
        if a >= mem.ram_start as u64 && a < mem.ram_start as u64 + (1 << 28) {
            ram = ram.max(e - mem.ram_start as u64);
            continue;
        }
        return Err(format!("section {} at {:#010x} is neither in flash nor in RAM", s.name, s.addr));
    }
    Ok(Usage { flash, ram })
}

/// Checks a usage against a memory: an error naming what is over. RAM
/// must leave the stack at least `stack_min` bytes.
pub fn check(u: &Usage, mem: &Memory) -> Result<String, String> {
    let line = format!(
        "flash {} of {} bytes ({:.1} %), RAM {} of {} bytes ({:.1} %), {} left for the stack (at least {})",
        u.flash,
        mem.flash_size,
        100.0 * u.flash as f64 / mem.flash_size as f64,
        u.ram,
        mem.ram_size,
        100.0 * u.ram as f64 / mem.ram_size as f64,
        (mem.ram_size as u64).saturating_sub(u.ram),
        mem.stack_min,
    );
    if u.flash > mem.flash_size as u64 || u.ram + mem.stack_min as u64 > mem.ram_size as u64 {
        return Err(format!("over budget: {}", line));
    }
    Ok(line)
}

/// The headroom budget_test keeps on the chip, and the book's budget
/// figure draws: flash use at most this percentage of the chip.
pub const FLASH_MAX_PERCENT: u64 = 90;

/// The headroom's other half: RAM left free for the stack, in bytes.
pub const STACK_MIN_FREE: u64 = 2 * 1024;

/// One block of the memory map: an allocated section, or a part of the
/// flash image no flash section covers (the initial values of RAM sections
/// such as .data, which the startup code copies to RAM).
#[derive(Debug, PartialEq)]
pub struct Block {
    pub name: String,
    /// "flash" or "ram".
    pub region: &'static str,
    pub start: u32,
    pub size: u32,
}

/// The name of a block of the image that no flash section covers.
pub const LOAD_IMAGE: &str = "(initial values of RAM sections)";

/// The firmware's memory map, by address. Each allocated section that is
/// not empty, which must lie wholly in flash or wholly in RAM; then each
/// part of a loadable segment in flash that no flash section covers,
/// taken from the program headers, so padding between them is in no
/// block.
pub fn memory_map(d: &[u8], elf: &Elf, mem: &Memory) -> Result<Vec<Block>, String> {
    let flash = (mem.flash_start as u64, end(mem.flash_start, mem.flash_size)?);
    let ram = (mem.ram_start as u64, end(mem.ram_start, mem.ram_size)?);
    let mut out = Vec::new();
    let mut covered = Vec::new();
    for s in elf.sections.iter().filter(|s| s.flags & SHF_ALLOC != 0 && s.size > 0) {
        let (a, e) = (s.addr as u64, end(s.addr, s.size)?);
        let region = if a >= flash.0 && a < flash.1 {
            if e > flash.1 {
                return Err(format!("section {} at {:#010x} runs past the end of flash", s.name, s.addr));
            }
            covered.push((a, e));
            "flash"
        } else if a >= ram.0 && a < ram.1 {
            if e > ram.1 {
                return Err(format!("section {} at {:#010x} runs past the end of RAM", s.name, s.addr));
            }
            "ram"
        } else {
            return Err(format!("section {} at {:#010x} is neither in flash nor in RAM", s.name, s.addr));
        };
        out.push(Block { name: s.name.clone(), region, start: s.addr, size: s.size });
    }
    // Checks the segments: in flash, and not overlapping.
    image(d, elf, mem)?;
    covered.sort();
    let mut segs: Vec<&Segment> = elf.segments.iter().filter(|s| s.filesz > 0).collect();
    segs.sort_by_key(|s| s.paddr);
    for seg in segs {
        let (mut a, e) = (seg.paddr as u64, end(seg.paddr, seg.filesz)?);
        for &(s0, s1) in &covered {
            if s1 <= a || s0 >= e {
                continue;
            }
            if s0 > a {
                out.push(Block { name: LOAD_IMAGE.into(), region: "flash", start: a as u32, size: (s0 - a) as u32 });
            }
            a = a.max(s1);
        }
        if a < e {
            out.push(Block { name: LOAD_IMAGE.into(), region: "flash", start: a as u32, size: (e - a) as u32 });
        }
    }
    out.sort_by_key(|b| b.start);
    Ok(out)
}
