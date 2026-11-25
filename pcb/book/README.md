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
| `//pcb:render_book` | `render_book/top.png`, `bottom.png` | The board in 3D, 1200 by 800 pixels asked; KiCad draws them a little smaller (1176 by 784 here). |
| `:placement_tsv` | `placement.tsv` | Where the assembler puts each part: designator, value, package, x and y in the board's frame (mm), rotation, side, and dnp. The book draws the assembly drawing from it. KiCad 9.0.9 cannot plot the fab layer without each part's value (`pcb export svg` has no `--exclude-value`), and on this board the values overlap. |
| `:fab_package_tsv` | `fab_package.tsv` | The files of JLCPCB's ZIP, with size and sha256, and the ZIP's own row last. The book sets it as a table. |

bazel_rules_kicad's `kicad_layers` plots each layer figure's SVG with the
pinned `kicad-cli pcb export svg`, and writes the epoch in place of the
date KiCad puts in the SVG's title. `svg_png` (`book.bzl`) draws each PNG
with the normalize toolchain's `svgpng`, at the dpi that gives the book's
exact width; `kicad_layers` takes a whole dpi, which misses it by a pixel
or two.

The checks:
- `:book_test`: the placement table agrees with `pcb/placement.py` part by
  part, and only J2 is DNP. The fab table lists the ZIP's files exactly.
  Each figure is under 300 KB, each PNG as wide as its figure, and no SVG
  keeps a date but the epoch. Also, on made-up input: the Excellon reader,
  and a hole off the board.
- `:book_determinism_test`: two builds give the same bytes.
