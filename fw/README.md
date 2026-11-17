<!-- SPDX-License-Identifier: Apache-2.0 -->
# Firmware

The sensor's firmware, in Rust, for the STM32F042F6: a Cortex-M0 with
32 KB of flash and 6 KB of RAM (target `thumbv6m-none-eabi`). The plan is
issue [#14](https://github.com/filmil/hdlf_example_sensor/issues/14). So
far it is the toolchain's proof: a binary that starts and sleeps.

```sh
bazel build //fw:fw //fw:fw_bin   # the ELF, and fw.bin, the raw flash image
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
- **`:fw`** builds for the platform `:stm32f042` whatever the build's own
  platform, so `bazel build //...` on a PC builds it too. It links with
  cortex-m-rt's `link.x` and this directory's `memory.x`, with
  `opt-level=z`, one codegen unit, fat LTO (set in `.bazelrc`) and
  `panic=abort`.
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
| `:budget_test` | The ELF fits 32 KB of flash and 6 KB of RAM, and prints the margin. The same firmware on a chip one byte too small must fail. |
| `:fw_determinism_test` | The ELF and `fw.bin` are the same bytes from two configurations. |
| `:licence_test` | Every crate of `Cargo.lock` is in `crate_licences.txt`, at its version, with a licence the project accepts: MIT, Apache-2.0, BSD, Zlib, or an OR that offers one. |
| `tools:elf_test` | The ELF reader, on a small ELF the test writes byte by byte. |

`crate_licences.txt` comes from crates.io's metadata for each locked
version. A change to `Cargo.lock` must update it, or the test fails.

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
