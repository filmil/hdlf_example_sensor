// SPDX-License-Identifier: Apache-2.0
//! fw_tables ELF BUDGET MEMMAP: writes the firmware's budget and memory
//! map as tables, for the book (bazel-cad-book draws them). Both come
//! from //fw/tools:elf, as //fw:budget_test's numbers do.
//!
//! BUDGET, one quantity a row (bytes, but for the percentage):
//! flash_size, flash_used, flash_max_percent, flash_cap, ram_size,
//! ram_used, stack_min, stack_min_free.
//!
//! MEMMAP, one block a row, by address (elf::memory_map): section, region
//! (flash or ram), start (0x and 8 hex digits), size (bytes).
use std::fmt::Write as _;
use std::process::ExitCode;

fn budget(u: &elf::Usage, m: &elf::Memory) -> String {
    let mut s = String::from("quantity\tvalue\n");
    for (k, v) in [
        ("flash_size", m.flash_size as u64),
        ("flash_used", u.flash),
        ("flash_max_percent", elf::FLASH_MAX_PERCENT),
        ("flash_cap", m.flash_size as u64 * elf::FLASH_MAX_PERCENT / 100),
        ("ram_size", m.ram_size as u64),
        ("ram_used", u.ram),
        ("stack_min", m.stack_min as u64),
        ("stack_min_free", elf::STACK_MIN_FREE),
    ] {
        writeln!(s, "{}\t{}", k, v).unwrap();
    }
    s
}

fn memmap(blocks: &[elf::Block]) -> String {
    let mut s = String::from("section\tregion\tstart\tsize\n");
    for b in blocks {
        writeln!(s, "{}\t{}\t{:#010x}\t{}", b.name, b.region, b.start, b.size).unwrap();
    }
    s
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: fw_tables ELF BUDGET MEMMAP".into());
    }
    let data = std::fs::read(&args[1]).map_err(|e| format!("{}: {}", args[1], e))?;
    let parsed = elf::parse(&data)?;
    let m = &elf::STM32F042F6;
    let u = elf::usage(&data, &parsed, m)?;
    let blocks = elf::memory_map(&data, &parsed, m)?;
    std::fs::write(&args[2], budget(&u, m)).map_err(|e| format!("{}: {}", args[2], e))?;
    std::fs::write(&args[3], memmap(&blocks)).map_err(|e| format!("{}: {}", args[3], e))
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("fw_tables: {}", e);
            ExitCode::FAILURE
        }
    }
}
