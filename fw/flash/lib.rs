// SPDX-License-Identifier: Apache-2.0
//! What //fw:flash runs, apart from finding its files, so CI can test it:
//! //fw:flash itself is manual, and builds only once the dfu-util mirror
//! exists.

/// The STM32 ROM bootloader's USB ID, as dfu-util 0.11's
/// doc/60-dfuse.rules lists it.
pub const DEVICE: &str = "0483:df11";

/// The start of the STM32F042's flash (fw/memory.x).
pub const FLASH_START: u32 = 0x0800_0000;

/// dfu-util's arguments to write `fw_bin` to the internal flash (alt
/// setting 0) from FLASH_START and leave DFU mode, the form dfu-util's man
/// page gives for STM32 parts.
pub fn dfu_args(fw_bin: &str) -> Vec<String> {
    vec![
        "-d".into(),
        DEVICE.into(),
        "-a".into(),
        "0".into(),
        "-s".into(),
        format!("{:#010x}:leave", FLASH_START),
        "-D".into(),
        fw_bin.into(),
    ]
}

/// //fw:flash takes no arguments. Anything given is an error rather than
/// ignored, so that `--help`, or a device selector the tool does not pass
/// on, never flashes a board by surprise.
pub fn check_args(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Ok(());
    }
    Err(format!(
        "//fw:flash takes no arguments, got {:?}. With JP1 closed and the board plugged in, run `bazel run //fw:flash` alone; with more than one STM32 bootloader on USB, unplug the others.",
        args
    ))
}
