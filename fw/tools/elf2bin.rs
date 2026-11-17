// SPDX-License-Identifier: Apache-2.0
//! elf2bin ELF BIN: writes the firmware's raw flash image, for DFU. It
//! refuses an image that does not fit the STM32F042F6's flash.
use std::process::ExitCode;

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        return Err("usage: elf2bin ELF BIN".into());
    }
    let data = std::fs::read(&args[1]).map_err(|e| format!("{}: {}", args[1], e))?;
    let elf = elf::parse(&data)?;
    let mem = &elf::STM32F042F6;
    let img = elf::image(&data, &elf, mem)?;
    if img.len() as u64 > mem.flash_size as u64 {
        return Err(format!("the image is {} bytes, the flash {}", img.len(), mem.flash_size));
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
