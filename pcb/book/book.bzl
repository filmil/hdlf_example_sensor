# SPDX-License-Identifier: Apache-2.0
"""The fab chapter's figures for bazel-cad-book: flat plots of the board's
layers, as SVG and PNG.

kicad_plot runs the pinned kicad-cli through bazel_rules_kicad's
toolchain, as kicad_render does, and svgpng (the normalize toolchain's
second tool) draws the PNG, at the dpi that gives the asked width. Both come from bazel_rules_kicad's private
run_tool.bzl and normalize.bzl: v0.1.0 has no public layer-plot rule. A
public one, kicad_layers, is requested upstream:
https://github.com/filmil/bazel_rules_kicad/issues/103.
"""

load("@hdlf_rules_kicad//kicad:defs.bzl", "KicadPcbInfo")
load("@hdlf_rules_kicad//kicad/private:normalize.bzl", "NORMALIZE_TOOLCHAIN_TYPE")
load("@hdlf_rules_kicad//kicad/private:run_tool.bzl", "RUN_TOOL_TOOLCHAINS", "run_tool")

_KICAD = Label("@hdlf_rules_kicad//kicad:toolchain_type")

def _png(ctx, svg, png):
    # svgpng is pure Go and reads no home or config, so it runs directly,
    # under book_png, which picks the dpi that gives `width` pixels.
    svgpng = ctx.toolchains[NORMALIZE_TOOLCHAIN_TYPE].tools["svgpng"]
    ctx.actions.run(
        executable = ctx.executable._book_png,
        arguments = ["--svgpng", svgpng.executable.path, "--width", str(ctx.attr.width), svg.path, png.path],
        inputs = [svg],
        tools = [svgpng],
        outputs = [png],
        mnemonic = "BookPng",
        progress_message = "Drawing %{output}",
    )

def _kicad_plot_impl(ctx):
    pcb = ctx.attr.pcb[KicadPcbInfo]
    raw = ctx.actions.declare_file(ctx.label.name + ".raw.svg")
    svg = ctx.actions.declare_file(ctx.label.name + ".svg")
    png = ctx.actions.declare_file(ctx.label.name + ".png")

    # Every option that shapes the plot is given, so a change in
    # kicad-cli's defaults cannot change it: one file, the board's area
    # only, no drawing sheet, drill holes at their size.
    run_tool(
        ctx,
        _KICAD,
        "kicad_cli",
        arguments = [
            "pcb",
            "export",
            "svg",
            "--mode-single",
            "--page-size-mode",
            "2",
            "--exclude-drawing-sheet",
            "--drill-shape-opt",
            "2",
            "--layers",
            ",".join(ctx.attr.layers),
        ] + ctx.attr.options + ["--output", raw.path, pcb.board.path],
        inputs = pcb.files,
        outputs = [raw],
        mnemonic = "KicadPlot",
        progress_message = "Plotting %s of %%{label}" % ", ".join(ctx.attr.layers),
    )

    # KiCad writes the date into the SVG's <title>.
    ctx.actions.run(
        executable = ctx.executable._svg_norm,
        arguments = [raw.path, svg.path],
        inputs = [raw],
        outputs = [svg],
        mnemonic = "BookSvgNorm",
        progress_message = "Removing the date from %{output}",
    )
    _png(ctx, svg, png)
    return [DefaultInfo(files = depset([svg, png]))]

_WIDTH_DOC = "The PNG's width in pixels: 1350 for a full-width figure in the book, 700 for a half-width one."

kicad_plot = rule(
    implementation = _kicad_plot_impl,
    doc = """Plots layers of a board flat: `<name>.svg` and `<name>.png`.""",
    attrs = {
        "pcb": attr.label(mandatory = True, providers = [KicadPcbInfo]),
        "layers": attr.string_list(mandatory = True, doc = "KiCad's layer names, such as F.Cu and Edge.Cuts."),
        "options": attr.string_list(doc = "More `kicad-cli pcb export svg` options, such as --mirror."),
        "width": attr.int(mandatory = True, doc = _WIDTH_DOC),
        "_book_png": attr.label(default = "//pcb/book:book_png", executable = True, cfg = "exec"),
        "_svg_norm": attr.label(default = "//pcb/book:svg_norm", executable = True, cfg = "exec"),
    },
    toolchains = [_KICAD, NORMALIZE_TOOLCHAIN_TYPE] + RUN_TOOL_TOOLCHAINS,
)

def _svg_png_impl(ctx):
    png = ctx.actions.declare_file(ctx.label.name + ".png")
    _png(ctx, ctx.file.src, png)
    return [DefaultInfo(files = depset([ctx.file.src, png]))]

svg_png = rule(
    implementation = _svg_png_impl,
    doc = """An SVG with no text, and `<name>.png` drawn from it by svgpng.""",
    attrs = {
        "src": attr.label(mandatory = True, allow_single_file = [".svg"]),
        "width": attr.int(mandatory = True, doc = _WIDTH_DOC),
        "_book_png": attr.label(default = "//pcb/book:book_png", executable = True, cfg = "exec"),
    },
    toolchains = [NORMALIZE_TOOLCHAIN_TYPE],
)
