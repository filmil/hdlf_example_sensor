<!-- SPDX-License-Identifier: Apache-2.0 -->
# Firmware

The sensor's firmware, in Rust with embassy, for the STM32F042F6: a
Cortex-M0 with 32 KB of flash and 6 KB of RAM (target
`thumbv6m-none-eabi`). The plan is issue
[#14](https://github.com/filmil/hdlf_example_sensor/issues/14).

## What it does

The board is a USB CDC serial device, VID 0x1209 and PID 0x0001
(pid.codes' test pair). Once a second it reads the HDC2080 and sends a
line such as `t=23.41 rh=45.2` to a terminal that has the port open
(DTR set). The
LED blinks on each reading, and stays on after a sensor error until a
reading works again.

- **Clocks:** HSI48 is both the system clock and the USB clock. The CRS
  trims it from the host's USB start-of-frame, so the board needs no
  crystal.
- **USB:** pins 17 and 18 become PA11 and PA12 after the `SYSCFG_CFGR1`
  remap, which `src/main.rs` sets; the D+ pull-up is inside the chip.
- **The sensor task:** every second it calls the driver's `measure`:
  trigger, wait for DRDY to rise on PA0 (EXTI, at most 100 ms), read
  DRDY_STATUS (which lowers the pin), read the results, format the line.
  Every I2C call has a 50 ms timeout, so a stuck bus fails rather than
  hangs. On any failure the LED stays on and the next tick calls `start`
  again: ID check, soft reset, 3 ms, the DRDY pin. `start` and `measure`
  live in `//fw:hdc2080`, generic over embedded-hal-async's traits, and
  are host-tested there with a fake bus, pin and delay.
- **The serial task** keeps only the latest reading: a new one replaces
  one not yet sent. It writes only while the terminal holds DTR, gives
  each write 100 ms, so a host that stops reading never stalls the
  device, and discards any reading from before a new connection.
- **Pins:** `src/main.rs` asserts at compile time that every pin it uses
  is the one `//fw:pins` gives from the netlist, so a change to the board
  that moves a pin stops the build.

The flash budget test reports, for this firmware: flash 24,112 of 32,768
bytes (73.6 %), and RAM 2,228 of 6,144 bytes, with 3,916 left for the
stack.

```sh
bazel build //fw:fw //fw:fw_bin   # fw.elf, and fw.bin, the raw flash image
bazel test //fw/...
```

## What builds it

- **Rust 1.100.0**, through rules_rust 0.75.0, with `rust-std` for the
  host and for `thumbv6m-none-eabi`. `MODULE.bazel` pins each tarball by
  sha256.
- **The crates** in `//third_party/crates`: `Cargo.toml`, locked in
  `Cargo.lock`. crate_universe builds each from its `.crate` file, pinned
  by `Cargo.lock`'s checksum. Targets depend on the aliases there
  (`//third_party/crates:embassy-stm32`), never on `@crates` directly.
  Each locked crate has a directory there, `<name>-<version>/`, with its
  licence files (`LICENSE`) and where each came from (`SOURCE.json`).
  To change the crates, edit `third_party/crates/Cargo.toml`, run
  `CARGO_BAZEL_REPIN=1 bazel mod tidy`, then `bazel run
  //tools/crate_licences` to refresh the licence directories, and update
  `crate_licences.txt`.
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
see. `third_party/crates/stm32-metapac-device-x.patch`, applied by a `crate.annotation` in
`MODULE.bazel`, copies the file into the build script's output
directory, which the link step does see.

## The checks

| Test | Checks |
|---|---|
| `:budget_test` | The ELF fits 32 KB of flash and 6 KB of RAM with at least 1 KB left for the stack, and prints the margin. The same firmware on a chip one byte too small, in flash or in RAM, must fail. The vector table is sound, and `fw.bin` is the ELF's image. |
| `:fw_determinism_test` | The ELF and `fw.bin` are the same bytes from two configurations. |
| `:licence_test` | Every crate of `Cargo.lock` has its directory under `//third_party/crates`, with a `LICENSE` that holds every file its `SOURCE.json` lists, and is in `crate_licences.txt`, once, at its version, and its SPDX expression offers MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause or Zlib. The one exception is unicode-ident: it is `(MIT OR Apache-2.0) AND Unicode-3.0`, and accepted because it only runs on the build machine, inside proc macros. |
| `tools:elf_test` | The ELF reader, on small ELF files the test writes byte by byte, malformed ones included. |
| `:pinmap_test`, `:pins_test` | The pin map: see below. |
| `:hdc2080_test` | The sensor's driver: see below. |

`crate_licences.txt` holds the `license` of each crate's own
`Cargo.toml`. A change to `Cargo.lock` must update it and the licence
directories (`bazel run //tools/crate_licences`), or the test fails.
Most crates ship their licence files; those that do not (cortex-m and the
embassy crates keep them at their repository's root) get them from their
repository at the commit the crate recorded, or one pinned by full SHA in
`tools/crate_licences/pins.json`.

Every approved crate is a dependency of `:fw_code` already, so this PR
shows each one builds for the Cortex-M0. The Cortex-M0 has no atomic
compare-and-swap, so `third_party/crates/Cargo.toml` turns on portable-atomic's
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

## Flashing the board

```sh
bazel run //fw:flash
```

`//fw:flash` writes `fw.bin` over the STM32F042's ROM USB DFU
bootloader. It is for the operator, at the board: CI never builds it
(it is `manual`), and no agent runs it. It runs on x86_64 Linux only, the
one platform its static dfu-util is built for.

1. With the board unplugged, close JP1, the solder jumper that pulls
   BOOT0 high. Then plug the board in. It comes up as the STM32
   bootloader, USB 0483:df11. Have no other STM32 bootloader on USB.
2. Run `bazel run //fw:flash`, with no arguments: it refuses any. It runs
   `dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D fw.bin`, which
   writes the internal flash from 0x08000000 and leaves DFU mode.
3. Unplug the board, open JP1 again, and plug it back in: it starts from
   flash.

On Linux the user needs access to the device, for example through the
udev rule in dfu-util's `doc/60-dfuse.rules`.

`dfu-util` comes from `//third_party/dfu_util`: dfu-util 0.11, statically
linked with libusb 1.0.30 (`//third_party/libusb`) and the musl C library
(`//third_party/musl`), so the host needs nothing installed. musl, not
glibc, so that no LGPL C library is linked into the binary. `bazel run //tools/dfu_util -- --out=DIR` builds it
from pinned sources in a pinned Ubuntu container with podman; two builds
give the same bytes, and the tool fails unless the binary has the sha256
`MODULE.bazel` pins. The binary is mirrored as the release
`mirror-dfu-util-0.11`, which the operator uploads with
`bazel run //tools/mirror -- --dry_run=false --built_dir=DIR`.
dfu-util is GPL-2.0-or-later and libusb LGPL-2.1-or-later. musl is MIT,
with some parts under BSD-2-Clause, BSD-3-Clause, ISC and other permissive
terms, as its `LICENSE` lists. Their licences are in `//third_party`. The
release holds the source of all three, as downloaded: dfu-util's,
libusb's, and Ubuntu's musl source package, since dfu-util's GPL asks for
the source of every library linked into a binary that is handed out. None of the three is part
of the firmware.

## The HDC2080 driver

`//fw:hdc2080` is a `no_std` crate on embedded-hal-async's `I2c` trait:
the sensor's driver, and the line the firmware prints for each reading.
Every register, bit and formula comes from TI's datasheet, SNAS678C (July
2021), cited by section and table in `hdc2080/lib.rs`.

- **Driver:**
  - `check_id` reads the manufacturer and device IDs (0x5449, 0x07D0);
  - `reset` sets SOFT_RES; the datasheet gives no settle time, so the
    firmware waits the 3 ms it gives for power-up;
  - `enable_drdy_pin` makes the DRDY pin (PA0) go high when a measurement
    completes; it stays high until `data_ready` reads DRDY_STATUS;
  - `trigger` starts one 14-bit humidity and temperature measurement;
  - `data_ready` reads DRDY_STATUS;
  - `read` reads all four result bytes in one transfer, LSB first, as the
    datasheet requires.
- **Conversions,** in integer fixed point (the Cortex-M0 has no FPU), each
  the exact value rounded once to the nearest unit:
  - temperature in hundredths of a degree, from Equation 2, with the
    datasheet's supply correction of 0.08 °C/V above 1.8 V (none below, as
    the datasheet says); at the board's 3.3 V that adds 0.12 °C;
  - humidity in tenths of a percent, from Equation 3.
- **The line:** `t=23.41 rh=45.2`, the format the plan in #14 gives. It is
  formatted by hand into a `heapless::Vec`, without `core::fmt`, to keep
  flash small. A reading gives at most 17 bytes; the buffer holds any
  input, so nothing is cut.

`:hdc2080_test` runs on the host:
- the conversions against Equations 1 to 3 in floating point, for every
  raw value, at supplies from 1.62 V to 3.6 V;
- the line for every temperature the board's sensor can give, and for
  the extremes of its input types;
- every I2C operation the driver makes, in order, on a fake bus that
  records them, answers from a script and checks every answer was used;
  and bus errors from each call, including the second write of
  `enable_drdy_pin`.

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
