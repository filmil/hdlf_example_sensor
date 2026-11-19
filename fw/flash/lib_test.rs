// SPDX-License-Identifier: Apache-2.0
//! //fw:flash's logic, on the host, in CI.
use std::ffi::{OsStr, OsString};
use std::path::Path;

#[test]
fn dfu_args_are_the_stm32_form() {
    let a: Vec<String> = flash_lib::dfu_args(OsStr::new("fw/fw.bin")).iter().map(|s| s.to_string_lossy().into_owned()).collect();
    assert_eq!(a.join(" "), "-d 0483:df11 -a 0 -s 0x08000000:leave -D fw/fw.bin");
}

#[test]
fn the_command_runs_dfu_util_with_them() {
    let c = flash_lib::command(Path::new("/x/dfu-util"), Path::new("/tmp/my fw/fw.bin"));
    assert_eq!(c.get_program(), "/x/dfu-util");
    let args: Vec<&OsStr> = c.get_args().collect();
    assert_eq!(args.len(), 8);
    // A path with a space stays one argument.
    assert_eq!(args[7], "/tmp/my fw/fw.bin");
}

#[cfg(unix)]
#[test]
fn a_non_utf8_path_passes_unchanged() {
    use std::os::unix::ffi::OsStrExt;
    let p = OsStr::from_bytes(b"/tmp/fw-\xff.bin");
    assert_eq!(flash_lib::dfu_args(p).last().unwrap(), p);
}

#[test]
fn no_arguments_are_accepted() {
    assert!(flash_lib::check_args(&[]).is_ok());
    for bad in [vec!["--help"], vec!["-S", "123"], vec!["fw.bin"]] {
        let args: Vec<OsString> = bad.iter().map(OsString::from).collect();
        let err = flash_lib::check_args(&args).unwrap_err();
        assert!(err.contains("takes no arguments"), "{}", err);
    }
}
