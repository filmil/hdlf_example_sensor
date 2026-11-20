<!-- SPDX-License-Identifier: Apache-2.0 -->
# Rust toolchain

The firmware (`//fw`) builds with Rust 1.100.0 through rules_rust 0.75.0.
The operator approved both in issue
[#14](https://github.com/filmil/hdlf_example_sensor/issues/14) (Q13).

The toolchain stays registered in `MODULE.bazel` (`rust.toolchain`).
That file pins seven tarballs by sha256 and fetches them from this
repository's release `mirror-rust-1.100.0` first, then from
static.rust-lang.org.
No build target uses this directory, because Bazel's toolchain resolution
picks the toolchain; only `//tools/mirror:mirror_test` reads it, to check
it.
This directory holds the licences of all seven tarballs, each file copied
unchanged from the pinned tarball named in the table.

## What the firmware ships

`LICENSE`, rustc's `COPYRIGHT`, says that the Rust project is
dual-licensed under Apache-2.0 and MIT "except as otherwise noted". The
standard library is linked into the firmware we ship, so its third-party
notices are here: `COPYRIGHT-library.html`, the file `LICENSE` names,
which gives each crate's licence and notice text in full.

Its crates are under MIT, Apache-2.0 (also with the LLVM exception),
BSD-2-Clause, Unicode-3.0, Unlicense, Zlib, BSL-1.0 and MPL-2.0, most of
them as one choice of an OR with MIT or Apache-2.0. It names no GPL code:
its "GPLv2" is the LLVM exception's clause on combining with GPLv2
software, and LGPL-2.1-or-later appears only as one choice of an OR, in
r-efi, which only UEFI targets use. The five licence texts it relies on
are here as `rustc-licenses-*.txt`, from the tarball's
`rustc/share/doc/rust/licenses/`.

## What stays in the tarballs

The toolchain is redistributed only as the unmodified mirror tarballs,
which carry their own notices. So these are not copied:

- the toolchain's own third-party list, `COPYRIGHT.html` (14 MB): it is
  `rustc/share/doc/rust/COPYRIGHT.html` in
  `rustc-1.100.0-x86_64-unknown-linux-gnu.tar.xz`, sha256
  `f1d0b1dec81dab6f523cd098507763487b0d4bd7fd2c87582f154128719be03b`;
- the other licence texts beside it (GPL-2.0, GPL-3.0, GCC exception,
  CC-BY-SA, OFL, ISC, NCSA), which serve the toolchain as a whole, not
  the standard library.

## Files

| Files | From |
|---|---|
| `LICENSE` (its `COPYRIGHT`), `LICENSE-APACHE`, `LICENSE-MIT` | `rustc-1.100.0-x86_64-unknown-linux-gnu` |
| `COPYRIGHT-library.html` | the same, `rustc/share/doc/rust/` |
| `rustc-licenses-{Apache-2.0,BSD-2-Clause,LLVM-exception,MIT,Unicode-3.0}.txt` | the same, `rustc/share/doc/rust/licenses/` |
| `cargo-LICENSE-APACHE`, `cargo-LICENSE-MIT`, `cargo-LICENSE-THIRD-PARTY` | `cargo-1.100.0-x86_64-unknown-linux-gnu` |
| `clippy-LICENSE-APACHE`, `clippy-LICENSE-MIT` | `clippy-1.100.0-x86_64-unknown-linux-gnu` |
| `rustfmt-LICENSE-APACHE`, `rustfmt-LICENSE-MIT` | `rustfmt-1.100.0-x86_64-unknown-linux-gnu` |
| `llvm-tools-LICENSE.TXT` (Apache-2.0 with LLVM exception) | `llvm-tools-1.100.0-x86_64-unknown-linux-gnu` |
| (none of their own) | `rust-std-1.100.0-x86_64-unknown-linux-gnu` and `rust-std-1.100.0-thumbv6m-none-eabi`: their `COPYRIGHT`, `LICENSE-APACHE` and `LICENSE-MIT` were byte for byte rustc's when copied |

## Checks

`//tools/mirror:mirror_test` checks, against `MODULE.bazel`:
- that this README names the pinned Rust version, the rules_rust version,
  the rustc tarball's sha256, and every pinned tarball;
- that the files of each component above are here.

A toolchain update must refresh this directory, or the test fails. The
test cannot check that rust-std's files still equal rustc's; whoever
updates the toolchain compares them, as was done for 1.100.0.
