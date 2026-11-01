# SPDX-License-Identifier: Apache-2.0
"""pcb_files: the sensor board's placed .kicad_pcb and its .kicad_pro, from gen.py."""

def _pcb_files_impl(ctx):
    fps = ctx.files.footprints
    roots = {f.path[:f.path.index("/footprints/") + len("/footprints")]: True for f in fps if "/footprints/" in f.path}
    if len(roots) != 1:
        fail("%s: footprints must come from one library tree, got %s" % (ctx.label, sorted(roots.keys())))
    mech = ctx.actions.declare_file(ctx.label.name + ".mech.json")
    ctx.actions.write(mech, ctx.attr.mech)
    args = ctx.actions.args()
    args.add("--mech", mech)
    args.add("--netlist", ctx.file.netlist)
    args.add("--footprints", roots.keys()[0])
    args.add("--pcb", ctx.outputs.board)
    args.add("--pro", ctx.outputs.project)
    if ctx.attr.bad:
        args.add("--bad", ctx.attr.bad)
    ctx.actions.run(
        executable = ctx.executable._gen,
        arguments = [args],
        inputs = [mech, ctx.file.netlist] + fps,
        outputs = [ctx.outputs.board, ctx.outputs.project],
        mnemonic = "SensorPcb",
        progress_message = "Generating the PCB %{label}",
    )
    return [DefaultInfo(files = depset([ctx.outputs.board, ctx.outputs.project]))]

pcb_files = rule(
    implementation = _pcb_files_impl,
    doc = "The sensor board's PCB and project, written by gen.py.",
    attrs = {
        "mech": attr.string(doc = "mech/mechanics.bzl's numbers, as JSON.", mandatory = True),
        "netlist": attr.label(doc = "The circuit's netlist.", allow_single_file = [".net"], mandatory = True),
        "footprints": attr.label(doc = "KiCad's footprint libraries.", allow_files = True, mandatory = True),
        "bad": attr.string(doc = "A known-bad PCB: missing_net or short.", values = ["", "missing_net", "short"]),
        "board": attr.output(mandatory = True),
        "project": attr.output(mandatory = True),
        "_gen": attr.label(default = ":gen", executable = True, cfg = "exec"),
    },
)
