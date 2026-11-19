// SPDX-License-Identifier: Apache-2.0
//! bazel run //fw:flash: writes fw.bin to the STM32F042's flash over its
//! ROM USB DFU bootloader (issue #14, step 5). fw/README.md gives the
//! steps. Manual only: no CI, and no agent, runs it.
//!
//! It runs the static dfu-util of //third_party/dfu_util with the
//! arguments of flash_lib::dfu_args:
//!
//!     dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D fw.bin
use runfiles::{rlocation, Runfiles};
use std::process::{Command, ExitCode};

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    flash_lib::check_args(&args)?;
    // The files come from the runfiles, so it works from any directory.
    let r = Runfiles::create().map_err(|e| format!("no runfiles: {}", e))?;
    let find = |p: &str| rlocation!(r, p).ok_or_else(|| format!("{} is not in the runfiles", p));
    let dfu_util = find(env!("DFU_UTIL"))?;
    let fw_bin = find(env!("FW_BIN"))?;
    let dfu_args = flash_lib::dfu_args(&fw_bin.to_string_lossy());
    println!("flash: {} {}", dfu_util.display(), dfu_args.join(" "));
    let status = Command::new(&dfu_util)
        .args(&dfu_args)
        .status()
        .map_err(|e| format!("cannot run {}: {}", dfu_util.display(), e))?;
    if !status.success() {
        return Err(format!("dfu-util failed: {}", status));
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("flash: {}", e);
            ExitCode::FAILURE
        }
    }
}
