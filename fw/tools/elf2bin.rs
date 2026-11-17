// SPDX-License-Identifier: Apache-2.0
//! elf2bin ELF BIN: writes the firmware's raw flash image, for DFU.
use std::process::ExitCode;

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        return Err("usage: elf2bin ELF BIN".into());
    }
    let data = std::fs::read(&args[1]).map_err(|e| format!("{}: {}", args[1], e))?;
    let elf = elf::parse(&data)?;
    let (img, start) = elf::image(&data, &elf)?;
    if start != elf::STM32F042F6.flash_start {
        return Err(format!("the image starts at {:#010x}, not flash at {:#010x}", start, elf::STM32F042F6.flash_start));
    }
    std::fs::write(&args[2], img).map_err(|e| format!("{}: {}", args[2], e))
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("elf2bin: {}", e);
            ExitCode::FAILURE
        }
    }
}
