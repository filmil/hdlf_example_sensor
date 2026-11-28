<!-- SPDX-License-Identifier: Apache-2.0 -->
# The firmware's crates

`Cargo.toml` and `Cargo.lock` here are what crate_universe builds the
firmware's crates from (`MODULE.bazel`), each pinned by `Cargo.lock`'s
sha256. Targets depend on the aliases in `BUILD.bazel`
(`//third_party/crates:embassy-stm32`), never on `@crates` directly.

- `crate_licences.txt`: each crate's SPDX licence, from its own
  `Cargo.toml`; `//fw:licence_test` checks it allows our use.
- `<name>-<version>/`, one per locked crate:
  - `LICENSE`: its licence files verbatim, each after a line naming
    it and where it came from;
  - `SOURCE.json`: each file's origin and sha256.

`bazel run //tools/crate_licences` writes those directories. Run it by
hand after `Cargo.lock` changes; `:licence_dirs_test` fails until you
do, and also if a directory's `LICENSE` differs by a byte from what its
`SOURCE.json` records. Most crates ship their licence files in the
`.crate`. Others, mostly cortex-m and embassy, keep them at their
repository's root, so they come from the repository at the commit the
crate recorded.

Three crates have no licence file upstream, only the licence their
`Cargo.toml` declares, so theirs are reconstructed. Their `SOURCE.json`
says `"reconstructed": true` and why, and `:licence_dirs_test` checks
that this table names each of them. The pins are in
`tools/crate_licences/pins.json`, by full commit SHA:

| Crate | Declares | Licence files |
|---|---|---|
| stm32-metapac 21.0.0 | MIT OR Apache-2.0 | stm32-data's own, added 2026-11-06, after the crate's release |
| sdio-host 0.9.0 | MIT OR Apache-2.0 | SPDX's standard texts; MIT's copyright line is from `Cargo.toml`'s authors and the 2022 publish year |
| void 1.0.2 | MIT | SPDX's standard text; the copyright line is from `Cargo.toml`'s author and the 2016 publish year |
