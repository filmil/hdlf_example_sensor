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
//!   how much. Two builds of the same sources give the same bytes
//!   (fw_determinism_test); a toolchain or crate update that changes the
//!   size updates RECORDED too, which shows what the update costs. Two
//!   PRs that both change the size both edit RECORDED's line, so git
//!   makes the second rebase, and its CI then checks the combination.
//! - Headroom: flash use at most FLASH_MAX_PERCENT (90 %) of the chip,
//!   and at least STACK_MIN_FREE (2 KB) of RAM left free for the stack.
//!   The last 10 % of flash (about 3.2 KB) is a reserve: the check fails
//!   when a change would spend it, so spending it is a choice, made by
//!   raising FLASH_MAX_PERCENT in the same PR, with the reason, where a
//!   reviewer sees it. Then a fix can still land without cutting a
//!   feature first; at 100 % even a one-line fix needs a cut. The hard
//!   limits of fits_the_chip stay: they are the chip's, whatever the cap.
//!   The stack: nothing here measures how deep it grows, only how much
//!   RAM is left for it. 2 KB is twice the hard minimum, slack for what
//!   an estimate would miss (interrupt frames over the executor's
//!   deepest poll).

/// The use when it was last recorded, in bytes.
const RECORDED: elf::Usage = elf::Usage { flash: 24112, ram: 2228 };

/// Flash use at most this percentage of the chip (elf.rs, so the book's
/// budget table has the same).
const FLASH_MAX_PERCENT: u64 = elf::FLASH_MAX_PERCENT;

/// RAM left free for the stack: at least this many bytes.
const STACK_MIN_FREE: u64 = elf::STACK_MIN_FREE;

/// Checks u against the headroom on m: a line with the margins, or an
/// error naming what is over.
fn headroom(u: &elf::Usage, m: &elf::Memory) -> Result<String, String> {
    let flash_max = m.flash_size as u64 * FLASH_MAX_PERCENT / 100;
    if u.flash > flash_max {
        return Err(format!("flash {} bytes, over {} % of {} ({} bytes)", u.flash, FLASH_MAX_PERCENT, m.flash_size, flash_max));
    }
    let free = (m.ram_size as u64).saturating_sub(u.ram);
    if free < STACK_MIN_FREE {
        return Err(format!("RAM {} bytes leaves {} for the stack, under {}", u.ram, free, STACK_MIN_FREE));
    }
    Ok(format!("headroom: flash {} bytes under {} %, stack {} bytes over {}", flash_max - u.flash, FLASH_MAX_PERCENT, free - STACK_MIN_FREE, STACK_MIN_FREE))
}

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
    match headroom(&u, m) {
        Ok(line) => println!("{}", line),
        Err(e) => panic!("{}", e),
    }
}

/// The headroom check at its edges, on made-up use: flash exactly at the
/// cap passes and one byte over fails; RAM leaving exactly STACK_MIN_FREE
/// passes and one byte less fails; RAM over the chip fails.
#[test]
fn headroom_at_its_edges() {
    let m = &elf::STM32F042F6;
    let flash_max = m.flash_size as u64 * FLASH_MAX_PERCENT / 100;
    let ram_max = m.ram_size as u64 - STACK_MIN_FREE;
    let at = |flash, ram| headroom(&elf::Usage { flash, ram }, m);
    assert!(at(flash_max, ram_max).is_ok(), "{:?}", at(flash_max, ram_max));
    assert!(at(flash_max + 1, ram_max).is_err());
    assert!(at(flash_max, ram_max + 1).is_err());
    assert!(at(flash_max, m.ram_size as u64 + 1).is_err());
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

/// The rows of a table the book draws, after checking its header; every
/// row has the header's number of columns.
fn table(var: &str, header: &[&str]) -> Vec<Vec<String>> {
    let text = String::from_utf8(read(var)).expect("UTF-8");
    let mut lines = text.lines();
    let head: Vec<&str> = lines.next().expect("a header").split('\t').collect();
    assert_eq!(head, header, "{}: header", var);
    let rows: Vec<Vec<String>> = lines.map(|l| l.split('\t').map(String::from).collect()).collect();
    for r in &rows {
        assert_eq!(r.len(), header.len(), "{}: row {:?}", var, r);
    }
    rows
}

/// //fw:budget_tsv has this test's numbers: the use, the chip, the cap and
/// the stack reserve.
#[test]
fn the_budget_table_agrees() {
    let (d, e) = firmware();
    let m = &elf::STM32F042F6;
    let u = elf::usage(&d, &e, m).expect("usage");
    let got: Vec<(String, u64)> = table("BUDGET_TSV", &["quantity", "value"]).into_iter().map(|r| (r[0].clone(), r[1].parse().expect("a number"))).collect();
    let want: Vec<(String, u64)> = [
        ("flash_size", m.flash_size as u64),
        ("flash_used", u.flash),
        ("flash_max_percent", FLASH_MAX_PERCENT),
        ("flash_cap", m.flash_size as u64 * FLASH_MAX_PERCENT / 100),
        ("ram_size", m.ram_size as u64),
        ("ram_used", u.ram),
        ("stack_min", m.stack_min as u64),
        ("stack_min_free", STACK_MIN_FREE),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v))
    .collect();
    assert_eq!(got, want);
}

/// //fw:memmap_tsv is elf::memory_map, row by row; its blocks do not
/// overlap, none is empty, and they end where the budget's use does: the
/// flash blocks at the image's end, the RAM blocks at the end of the last
/// RAM section.
#[test]
fn the_memory_map_agrees() {
    let (d, e) = firmware();
    let m = &elf::STM32F042F6;
    let u = elf::usage(&d, &e, m).expect("usage");
    let rows = table("MEMMAP_TSV", &["section", "region", "start", "size"]);
    let parsed: Vec<(String, String, u64, u64)> = rows
        .iter()
        .map(|r| {
            let hex = r[2].strip_prefix("0x").unwrap_or_else(|| panic!("{}: start {} is not 0x hex", r[0], r[2]));
            assert_eq!(hex.len(), 8, "{}: start {}", r[0], r[2]);
            (r[0].clone(), r[1].clone(), u64::from_str_radix(hex, 16).expect("a hex start"), r[3].parse().expect("a size"))
        })
        .collect();
    let want: Vec<(String, String, u64, u64)> = elf::memory_map(&d, &e, m)
        .expect("memory map")
        .into_iter()
        .map(|b| (b.name, b.region.to_string(), b.start as u64, b.size as u64))
        .collect();
    assert_eq!(parsed, want);
    let mut ends = (m.flash_start as u64, m.ram_start as u64);
    let mut last_end = 0u64;
    for (name, region, start, size) in &parsed {
        assert!(*size > 0, "{} is empty", name);
        assert!(*start >= last_end, "{} overlaps the block before it", name);
        last_end = start + size;
        let cell = if region == "flash" { &mut ends.0 } else { &mut ends.1 };
        *cell = (*cell).max(start + size);
    }
    assert_eq!(ends.0 - m.flash_start as u64, u.flash, "the flash blocks end elsewhere than the image");
    assert_eq!(ends.1 - m.ram_start as u64, u.ram, "the RAM blocks end elsewhere than the RAM use");
}
