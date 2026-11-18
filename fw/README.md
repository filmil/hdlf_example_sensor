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
| `:hdc2080_test` | The sensor's driver: see below. |

`crate_licences.txt` holds the `license` of each crate's own
`Cargo.toml`. A change to `Cargo.lock` must update it, or the test fails.

Every approved crate is a dependency of `:fw_code` already, so this PR
shows each one builds for the Cortex-M0. The Cortex-M0 has no atomic
compare-and-swap, so `Cargo.toml` turns on portable-atomic's
`critical-section` feature, which cortex-m's single-core critical
section serves.

## The pin map

`//fw:pins` is a `no_std` crate with one constant per MCU net the
firmware uses. A net on a peripheral signal with an alternate function is
an `AfPin`: port, pin number and alternate function. Any other net (a
GPIO, BOOT0, and USB, whose pins are analog and have none) is a `Pin`.
`//fw:pins_rs` generates the crate at build time from the board's netlist
(`//elec:netlist`), so the firmware cannot drift from the board.
`pins.json` names the chip, the part U1 must be, and the nets:

| Net | Must be |
|---|---|
| `LED`, `DRDY` | a port pin |
| `I2C_SDA`, `I2C_SCL` | I2C1's SDA and SCL |
| `USB_DP`, `USB_DM` | USB's DP and DM |
| `BOOT0` | PB8: BOOT0 shares pin 1 with it (PB8-BOOT0, DocID025832 Rev 4, Table 13) |

`pinmap/pinmap.py` checks, and the build fails, naming every problem:
- **U1 is the part `pins.json` names**: its value, its KiCad library and
  symbol, and its footprint, as the netlist records them. Another package
  of the chip numbers its pins differently.
- **each net is on exactly one pin of U1**, and no two nets share a pin;
- **that pin can do what the net needs.** Its name comes from the symbol
  the netlist names for U1, in `@kicad_libs`. What that port can do comes
  from stm32-metapac's metadata for the chip.

The metadata is the chip's `chips/stm32f042f6/metadata.rs` and the
numbered shard it includes. The generator follows the `include!` and
checks the chip's name, so a metapac update that renumbers the shards
stops the build until `MODULE.bazel`'s `chip_metadata` filegroup names
the new one. It also fails if the metadata holds entries it does not
parse, rather than dropping them.

Pins 17 and 18 have two names, "PA9/PA11" and "PA10/PA12": the second
after the remap in `SYSCFG_CFGR1`. The remap is one setting for the whole
chip, so the generator tries the board with it off and with it on, and
`REMAP_PA11_PA12` says which fits. USB needs it on. Any other two-name pin
is an error.

`:pinmap_test` runs the generator on the real netlist, and on edits of it
that must fail, one for each check above. `:pins_test` checks the
generated crate against what `elec/circuit.py` wires.

## The HDC2080 driver

`//fw:hdc2080` is a `no_std` crate on embedded-hal-async's `I2c` trait:
the sensor's driver, and the line the firmware prints for each reading.
Every register, bit and formula comes from TI's datasheet, SNAS678C (July
2021), cited by section and table in `hdc2080/lib.rs`.

- **Driver:**
  - `check_id` reads the manufacturer and device IDs (0x5449, 0x07D0);
  - `reset` sets SOFT_RES;
  - `enable_drdy_pin` makes the DRDY pin (PA0) go high when a measurement
    completes;
  - `trigger` starts one 14-bit humidity and temperature measurement;
  - `data_ready` reads DRDY_STATUS;
  - `read` reads all four result bytes in one transfer, LSB first, as the
    datasheet requires.
- **Conversions,** in integer fixed point (the Cortex-M0 has no FPU),
  rounded to the nearest unit:
  - temperature in hundredths of a degree, from Equation 2, with the
    datasheet's supply correction of 0.08 °C/V above 1.8 V; at the board's
    3.3 V that adds 0.12 °C;
  - humidity in tenths of a percent, from Equation 3.
- **The line:** `t=23.41 rh=45.2`, the format the plan in #14 gives. It is
  formatted by hand into a `heapless::Vec`, without `core::fmt`, to keep
  flash small.

`:hdc2080_test` runs on the host:
- the conversions against Equations 1 to 3 in floating point, across the
  whole raw range and at its edges;
- the line, from -40.50 °C to 124.50 °C;
- every I2C transaction the driver makes, on a fake bus that records them
  and answers from a script, and bus errors passing through.

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
