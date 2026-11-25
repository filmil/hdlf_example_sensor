# SPDX-License-Identifier: Apache-2.0
"""The fab chapter's PNGs for bazel-cad-book, drawn from SVGs at the exact
width the book asks for.

bazel_rules_kicad's kicad_layers plots the layers; its PNG takes a whole
dpi, which misses the book's widths by a pixel or two. So the PNGs are
drawn here instead: svgpng (the normalize toolchain's second tool) runs
under book_png, which picks the dpi that gives the asked width.
"""

_NORMALIZE = Label("@hdlf_rules_kicad//kicad:normalize_toolchain_type")

def _svg_png_impl(ctx):
    png = ctx.outputs.out or ctx.actions.declare_file(ctx.label.name + ".png")

    # svgpng is pure Go and reads no home or config, so it runs directly.
    svgpng = ctx.toolchains[_NORMALIZE].tools["svgpng"]
    ctx.actions.run(
        executable = ctx.executable._book_png,
        arguments = ["--svgpng", svgpng.executable.path, "--width", str(ctx.attr.width), ctx.file.src.path, png.path],
        inputs = [ctx.file.src],
        tools = [svgpng],
        outputs = [png],
        mnemonic = "BookPng",
        progress_message = "Drawing %{output}",
    )
    return [DefaultInfo(files = depset([ctx.file.src, png]))]

svg_png = rule(
    implementation = _svg_png_impl,
    doc = """An SVG, and a PNG drawn from it by svgpng, `width` pixels wide.""",
    attrs = {
        "src": attr.label(mandatory = True, allow_single_file = [".svg"]),
        "out": attr.output(doc = "The PNG; `<name>.png` if not given."),
        "width": attr.int(
            mandatory = True,
            doc = "The PNG's width in pixels: 1350 for a full-width figure in the book, 700 for a half-width one.",
        ),
        "_book_png": attr.label(default = "//pcb/book:book_png", executable = True, cfg = "exec"),
    },
    toolchains = [_NORMALIZE],
)
