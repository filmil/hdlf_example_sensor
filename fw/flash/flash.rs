// SPDX-License-Identifier: Apache-2.0
//! bazel run //fw:flash: writes fw.bin to the STM32F042's flash over its
//! ROM USB DFU bootloader (issue #14, step 5). fw/README.md gives the
//! steps. Manual only: no CI, and no agent, runs it. The logic, which CI
//! builds and tests, is in lib.rs (//fw:flash_lib).
use std::process::ExitCode;

fn main() -> ExitCode {
    match flash_lib::main(env!("DFU_UTIL"), env!("FW_BIN")) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("flash: {}", e);
            ExitCode::FAILURE
        }
    }
}
