<!-- SPDX-License-Identifier: Apache-2.0 -->
# The fab chapter's figures

bazel-cad-book pins this repository and takes these files through its
`example_file` rule for its fab-package chapter, so its figures follow the
board. Each figure is an SVG and a PNG made from it. The PNGs are sized
for the book at 300 dpi: 700 pixels for a half-width figure (1350 would
be full width), and each is under 300 KB.

| Target | Files | What |
|---|---|---|
| `:f_cu`, `:b_cu`, `:f_silk` | `f_cu.svg/.png` and so on | Top copper, bottom copper (mirrored, as seen from below), and top silkscreen with the solder-mask openings; each with the outline. Half width. |
| `:drill` | `drill.svg/.png` | The holes from the Excellon files JLCPCB gets, at their size, one colour per drill; the outline and the slot from `mech/mechanics.bzl`. No text: the book adds the legend. Half width. |
| `//pcb:render_book` | `render_book/top.png`, `bottom.png` | The board in 3D, 1200 by 800 pixels. |
| `:placement_tsv` | `placement.tsv` | Where the assembler puts each part: designator, value, package, x and y in the board's frame (mm), rotation, side, and dnp. The book draws the assembly drawing from it. KiCad 9.0.9 cannot plot the fab layer without each part's value (`pcb export svg` has no `--exclude-value`), and on this board the values overlap. |
| `:fab_package_tsv` | `fab_package.tsv` | The files of JLCPCB's ZIP, with size and sha256, and the ZIP's own row last. The book sets it as a table. |

`kicad_plot` (`book.bzl`) runs the pinned `kicad-cli pcb export svg`
through bazel_rules_kicad's toolchain, as `kicad_render` does, removes the
date KiCad writes into the SVG, and draws the PNG with the toolchain's
`svgpng`. It loads bazel_rules_kicad's private `run_tool.bzl` and
`normalize.bzl`, since v0.1.0 has no public layer-plot rule. A refactor
of those files upstream would break it, so a public `kicad_layers` rule is
requested in https://github.com/filmil/bazel_rules_kicad/issues/103; once
it exists, this rule goes.

The checks:
- `:book_test`: the placement table agrees with `pcb/placement.py` part by
  part, and only J2 is DNP. The fab table lists the ZIP's files exactly.
  Each figure is under 300 KB, each PNG as wide as its figure, and no SVG
  keeps a date. Also, on made-up input: the date remover, the Excellon
  reader, and a hole off the board.
- `:book_determinism_test`: two builds give the same bytes.
