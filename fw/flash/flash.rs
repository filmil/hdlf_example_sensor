// SPDX-License-Identifier: Apache-2.0
//! bazel run //fw:flash: writes fw.bin to the STM32F042's flash over its
//! ROM USB DFU bootloader (issue #14, step 5). Close JP1 (BOOT0 high), plug
//! the board in, and run it; open JP1 again afterwards. Manual only: no
//! CI, and no agent, runs it.
//!
//! It runs the static dfu-util of //tools/dfu_util:
//!
//!     dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D fw.bin
//!
//! 0483:df11 is the STM32 bootloader in dfu-util 0.11's
//! doc/60-dfuse.rules; "-a 0 -s ADDRESS:leave -D FILE" writes the internal
//! flash at ADDRESS and leaves DFU mode, the form dfu-util's man page gives
//! for STM32 parts. 0x08000000 is the start of flash (fw/memory.x).
use std::process::{Command, ExitCode};

fn main() -> ExitCode {
    // bazel run starts this in its runfiles, where these paths resolve.
    let dfu_util = env!("DFU_UTIL");
    let fw_bin = env!("FW_BIN");
    let args = ["-d", "0483:df11", "-a", "0", "-s", "0x08000000:leave", "-D", fw_bin];
    println!("flash: {} {}", dfu_util, args.join(" "));
    match Command::new(dfu_util).args(args).status() {
        Ok(s) if s.success() => ExitCode::SUCCESS,
        Ok(s) => {
            eprintln!("flash: dfu-util failed: {}", s);
            ExitCode::FAILURE
        }
        Err(e) => {
            eprintln!("flash: cannot run {}: {}", dfu_util, e);
            ExitCode::FAILURE
        }
    }
}
