// SPDX-License-Identifier: Apache-2.0
//! //fw:flash's arguments, on the host, in CI.

#[test]
fn dfu_args_are_the_stm32_form() {
    assert_eq!(
        flash_lib::dfu_args("fw/fw.bin").join(" "),
        "-d 0483:df11 -a 0 -s 0x08000000:leave -D fw/fw.bin"
    );
}

#[test]
fn a_path_with_spaces_stays_one_argument() {
    let a = flash_lib::dfu_args("/tmp/my fw/fw.bin");
    assert_eq!(a.last().unwrap(), "/tmp/my fw/fw.bin");
    assert_eq!(a.len(), 8);
}

#[test]
fn no_arguments_are_accepted() {
    assert!(flash_lib::check_args(&[]).is_ok());
    for bad in [vec!["--help"], vec!["-S", "123"], vec!["fw.bin"]] {
        let args: Vec<String> = bad.iter().map(|s| s.to_string()).collect();
        let err = flash_lib::check_args(&args).unwrap_err();
        assert!(err.contains("takes no arguments"), "{}", err);
    }
}
