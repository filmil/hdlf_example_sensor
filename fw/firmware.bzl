# SPDX-License-Identifier: Apache-2.0
"""firmware: a rust_binary built as the STM32F042's firmware.

Bazel builds in fastbuild by default, and a rust_binary's rustc_flags
reach only its own crate. This rule's transition sets, for the binary and
every crate under it:

- the platform //fw:stm32f042 (thumbv6m-none-eabi);
- compilation mode opt, so no crate keeps debug assertions or overflow
  checks;
- fat LTO, with the bitcode it needs in every crate;
- opt-level z, one codegen unit and panic=abort, through rules_rust's
  extra_rustc_flags, which come after the mode's opt-level on rustc's line
  and reach no exec-configuration tool, such as a proc macro.

So the firmware is the same bytes whatever the command line's mode or
.bazelrc, and the host's tools and tests keep their own settings.
"""

_PLATFORM = "//command_line_option:platforms"
_MODE = "//command_line_option:compilation_mode"
_LTO = "@rules_rust//rust/settings:lto"
_FLAGS = "@rules_rust//rust/settings:extra_rustc_flags"

FLAGS = [
    "-Copt-level=z",
    "-Ccodegen-units=1",
    "-Cpanic=abort",
]

def _firmware_transition_impl(settings, attr):
    return {
        _PLATFORM: [str(attr.platform)],
        _MODE: "opt",
        _LTO: "fat",
        _FLAGS: FLAGS,
    }

_firmware_transition = transition(
    implementation = _firmware_transition_impl,
    inputs = [],
    outputs = [_PLATFORM, _MODE, _LTO, _FLAGS],
)

def _firmware_impl(ctx):
    src = ctx.attr.binary[0][DefaultInfo].files_to_run.executable
    out = ctx.actions.declare_file(ctx.label.name + ".elf")
    ctx.actions.symlink(output = out, target_file = src)
    return [DefaultInfo(files = depset([out]))]

firmware = rule(
    implementation = _firmware_impl,
    doc = "The ELF of `binary`, built for `platform` as firmware (see the file's doc).",
    attrs = {
        "binary": attr.label(
            mandatory = True,
            cfg = _firmware_transition,
            doc = "The rust_binary.",
        ),
        "platform": attr.label(
            mandatory = True,
            doc = "The chip's platform.",
        ),
    },
)
