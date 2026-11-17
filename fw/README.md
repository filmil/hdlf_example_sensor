<!-- SPDX-License-Identifier: Apache-2.0 -->
# Firmware

The sensor's firmware, in Rust, for the STM32F042F6: a Cortex-M0 with
32 KB of flash and 6 KB of RAM (target `thumbv6m-none-eabi`). The plan is
issue [#14](https://github.com/filmil/hdlf_example_sensor/issues/14). So
far it is the toolchain's proof: a binary that starts and sleeps.

```sh
bazel build //fw:fw //fw:fw_bin   # fw.elf, and fw.bin, the raw flash image
bazel test //fw/...
```

## What builds it

- **Rust 1.100.0**, through rules_rust 0.75.0, with `rust-std` for the
  host and for `thumbv6m-none-eabi`. `MODULE.bazel` pins each tarball by
  sha256.
- **The crates** in `Cargo.toml`, locked in `Cargo.lock`. crate_universe
  builds each from its `.crate` file, pinned by `Cargo.lock`'s checksum.
  To change them, edit `Cargo.toml` and run
  `CARGO_BAZEL_REPIN=1 bazel mod tidy`.
- **`:fw`** is `fw.elf`: the `firmware` rule (`firmware.bzl`) builds
  `:fw_code` and every crate under it for the platform `:stm32f042`, in
  opt mode, with fat LTO, `opt-level=z`, one codegen unit and
  `panic=abort`, whatever the command line's mode. `bazel build //...` on
  a PC builds it too, and skips `:fw_code` itself. It links with
  cortex-m-rt's `link.x` and this directory's `memory.x`. rules_rust
  remaps the build's paths, so none reaches the ELF.
- **`:fw_bin`** is `fw.bin`, the image a DFU flash writes, made by
  `tools:elf2bin`.

stm32-metapac's build script points the linker at the chip's `device.x`
in the crate's own source directory, which Bazel's link step does not
see. `stm32-metapac-device-x.patch`, applied by a `crate.annotation` in
`MODULE.bazel`, copies the file into the build script's output
directory, which the link step does see.

## The checks

| Test | Checks |
|---|---|
| `:budget_test` | The ELF fits 32 KB of flash and 6 KB of RAM with at least 1 KB left for the stack, and prints the margin. The same firmware on a chip one byte too small, in flash or in RAM, must fail. The vector table is sound, and `fw.bin` is the ELF's image. |
| `:fw_determinism_test` | The ELF and `fw.bin` are the same bytes from two configurations. |
| `:licence_test` | Every crate of `Cargo.lock` is in `crate_licences.txt`, once, at its version, and its SPDX expression offers MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause or Zlib. The one exception is unicode-ident: it is `(MIT OR Apache-2.0) AND Unicode-3.0`, and accepted because it only runs on the build machine, inside proc macros. |
| `tools:elf_test` | The ELF reader, on small ELF files the test writes byte by byte, malformed ones included. |
| `:pinmap_test`, `:pins_test` | The pin map: see below. |

`crate_licences.txt` holds the `license` of each crate's own
`Cargo.toml`. A change to `Cargo.lock` must update it, or the test fails.

Every approved crate is a dependency of `:fw_code` already, so this PR
shows each one builds for the Cortex-M0. The Cortex-M0 has no atomic
compare-and-swap, so `Cargo.toml` turns on portable-atomic's
`critical-section` feature, which cortex-m's single-core critical
section serves.

## The pin map

`//fw:pins` is a `no_std` crate with one constant per MCU net the
firmware uses: its port and pin number and, for a peripheral signal, its
alternate function. `//fw:pins_rs` generates it at build time from the
board's netlist (`//elec:netlist`), so the firmware cannot drift from the
board. `pins.json` lists the nets and what each pin must do:

| Net | Must be |
|---|---|
| `LED`, `DRDY` | a port pin |
| `I2C_SDA`, `I2C_SCL` | I2C1's SDA and SCL |
| `USB_DP`, `USB_DM` | USB's DP and DM |
| `BOOT0` | PB8: BOOT0 shares pin 1 with it (PB8-BOOT0, DocID025832 Rev 4, Table 13) |

`pinmap/pinmap.py` checks each net against three sources:
- the netlist, for the pin of U1 it is on;
- the KiCad symbol the board uses (`STM32F042F6Px`), for that pin's name;
- stm32-metapac's metadata for the chip, for what that port can do.

The build fails, naming every problem, if a net is missing, is on more
than one pin, or sits on a pin without its function. Pins 17 and 18 have
two names, "PA9/PA11" and "PA10/PA12": the second after the remap in
`SYSCFG_CFGR1`. The remap is one setting for the whole chip, so the
generator tries the board with it off and with it on, and
`REMAP_PA11_PA12` says which fits. USB needs it on.

`:pinmap_test` runs the generator on the real netlist and on edits of it
that must fail. `:pins_test` checks the generated crate against what
`elec/circuit.py` wires.

## Where the downloads come from

The Rust tarballs and the crates are mirrored as releases of this
repository (`tools/mirror`), and fetched from there first:

- `mirror-rust-1.100.0` holds the Rust tarballs: `MODULE.bazel` names it
  first, static.rust-lang.org second.
- `mirror-crates-1` holds the crates. crate_universe knows only
  static.crates.io, so `bazel_downloader.cfg` rewrites each crate's URL to
  the mirror first, then crates.io.

Bazel checks the same sha256 whichever URL answers.
`//tools/mirror:mirror_test` keeps the mirror's manifest equal to what
`MODULE.bazel` and `Cargo.lock` fetch. `bazel run //tools/mirror`
downloads every upstream file and checks it against the manifest. The
operator uploads with `bazel run //tools/mirror -- --dry_run=false`. A
crate added later goes to a new release, `mirror-crates-2`, with its own
line in `bazel_downloader.cfg`, since a release's assets are never
replaced.
