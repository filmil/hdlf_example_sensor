// SPDX-License-Identifier: Apache-2.0
//! //fw:flash's logic, so that CI builds and tests it: //fw:flash itself is
//! manual, and builds only once the dfu-util mirror exists. flash.rs only
//! calls `main` with its two runfiles paths.
use std::ffi::{OsStr, OsString};
use std::path::Path;
use std::process::Command;

/// The STM32 ROM bootloader's USB ID, as dfu-util 0.11's
/// doc/60-dfuse.rules lists it.
pub const DEVICE: &str = "0483:df11";

/// The start of the STM32F042's flash (fw/memory.x).
pub const FLASH_START: u32 = 0x0800_0000;

/// dfu-util's arguments to write `fw_bin` to the internal flash (alt
/// setting 0) from FLASH_START and leave DFU mode, the form dfu-util's man
/// page gives for STM32 parts. The path is passed as it is, never through
/// UTF-8.
pub fn dfu_args(fw_bin: &OsStr) -> Vec<OsString> {
    let mut a: Vec<OsString> = ["-d", DEVICE, "-a", "0", "-s"].iter().map(OsString::from).collect();
    a.push(format!("{:#010x}:leave", FLASH_START).into());
    a.push("-D".into());
    a.push(fw_bin.to_owned());
    a
}

/// The dfu-util command //fw:flash runs.
pub fn command(dfu_util: &Path, fw_bin: &Path) -> Command {
    let mut c = Command::new(dfu_util);
    c.args(dfu_args(fw_bin.as_os_str()));
    c
}

/// //fw:flash takes no arguments. Anything given is an error rather than
/// ignored, so that `--help`, or a device selector the tool does not pass
/// on, never flashes a board by surprise. Arguments are OS strings, so a
/// non-UTF-8 one is an error too, not a panic.
pub fn check_args(args: &[OsString]) -> Result<(), String> {
    if args.is_empty() {
        return Ok(());
    }
    Err(format!(
        "//fw:flash takes no arguments, got {:?}. With JP1 closed and the board plugged in, run `bazel run //fw:flash` alone; with more than one STM32 bootloader on USB, unplug the others.",
        args
    ))
}

/// //fw:flash: checks the arguments, finds dfu-util and fw.bin in the
/// runfiles by their rlocation paths, and runs dfu-util.
pub fn main(dfu_util: &str, fw_bin: &str) -> Result<(), String> {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    check_args(&args)?;
    let r = runfiles::Runfiles::create().map_err(|e| format!("no runfiles: {}", e))?;
    let find = |p: &str| r.rlocation(p).ok_or_else(|| format!("{} is not in the runfiles", p));
    let dfu_util = find(dfu_util)?;
    let fw_bin = find(fw_bin)?;
    let mut c = command(&dfu_util, &fw_bin);
    println!("flash: {:?}", c);
    let status = c.status().map_err(|e| format!("cannot run {}: {}", dfu_util.display(), e))?;
    if !status.success() {
        return Err(format!("dfu-util failed: {}", status));
    }
    Ok(())
}
