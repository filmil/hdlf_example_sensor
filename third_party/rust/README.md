<!-- SPDX-License-Identifier: Apache-2.0 -->
# Rust toolchain

The firmware (`//fw`) builds with Rust 1.100.0 through rules_rust 0.75.0.
The operator approved both in issue
[#14](https://github.com/filmil/hdlf_example_sensor/issues/14) (Q13).

The toolchain stays registered in `MODULE.bazel` (`rust.toolchain`).
That file pins seven tarballs by sha256 and fetches them from this
repository's release `mirror-rust-1.100.0` first, then from
static.rust-lang.org.
No target refers to this directory by label, because Bazel's toolchain
resolution picks the toolchain.
This directory holds the licences of all seven tarballs, each file copied
unchanged from the pinned tarball named in the table.

`LICENSE`, rustc's `COPYRIGHT`, says that the Rust project is
dual-licensed under Apache-2.0 and MIT "except as otherwise noted". The
third-party parts of the standard library, which is linked into the
firmware we ship, and their licences are in `rustc-COPYRIGHT-library.html`,
with the licence texts it names in `rustc-licenses-*`.

The toolchain's own third-party list, `COPYRIGHT.html`, is not copied
here: it is 14 MB, and the toolchain is redistributed only as the
unmodified mirror tarballs, which contain it. It is
`rustc/share/doc/rust/COPYRIGHT.html` in
`rustc-1.100.0-x86_64-unknown-linux-gnu.tar.xz`, sha256
`f1d0b1dec81dab6f523cd098507763487b0d4bd7fd2c87582f154128719be03b`.

| Files | From |
|---|---|
| `LICENSE` (its `COPYRIGHT`), `LICENSE-APACHE`, `LICENSE-MIT` | `rustc-1.100.0-x86_64-unknown-linux-gnu` |
| `rustc-COPYRIGHT-library.html` | the same, `rustc/share/doc/rust/` |
| `rustc-licenses-*.txt` (12 texts) | the same, `rustc/share/doc/rust/licenses/` |
| `cargo-LICENSE-APACHE`, `cargo-LICENSE-MIT`, `cargo-LICENSE-THIRD-PARTY` | `cargo-1.100.0-x86_64-unknown-linux-gnu` |
| `clippy-LICENSE-APACHE`, `clippy-LICENSE-MIT` | `clippy-1.100.0-x86_64-unknown-linux-gnu` |
| `rustfmt-LICENSE-APACHE`, `rustfmt-LICENSE-MIT` | `rustfmt-1.100.0-x86_64-unknown-linux-gnu` |
| `llvm-tools-LICENSE.TXT` (Apache-2.0 with LLVM exception) | `llvm-tools-1.100.0-x86_64-unknown-linux-gnu` |
| (none of their own) | `rust-std-1.100.0-x86_64-unknown-linux-gnu` and `rust-std-1.100.0-thumbv6m-none-eabi`: their `COPYRIGHT`, `LICENSE-APACHE` and `LICENSE-MIT` are byte for byte rustc's |

`//tools/mirror:mirror_test` checks that this README names the version
`MODULE.bazel` pins, and that every pinned component has its files here.
A toolchain update must refresh this directory, or that test fails.
