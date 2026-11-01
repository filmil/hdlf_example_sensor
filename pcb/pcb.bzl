# SPDX-License-Identifier: Apache-2.0
"""pcb_files: the sensor board's placed .kicad_pcb and its .kicad_pro, from gen.py."""

def _pcb_files_impl(ctx):
    fps = ctx.files.footprints
    # Each footprint is <root>/<library>.pretty/<name>.kicad_mod; gen.py
    # takes <root>.
    roots = {}
    for f in fps:
        if f.extension != "kicad_mod" or not f.dirname.endswith(".pretty"):
            fail("%s: %s is not a footprint in a <library>.pretty directory" % (ctx.label, f.path))
        roots[f.dirname.rpartition("/")[0]] = True
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
        "bad": attr.string(
            doc = "A known-bad PCB for the parity test: missing_net or short.",
            values = ["", "missing_net", "short"],
        ),
        "board": attr.output(mandatory = True),
        "project": attr.output(mandatory = True),
        "_gen": attr.label(default = ":gen", executable = True, cfg = "exec"),
    },
)

def _spoiled_pcb_impl(ctx):
    args = ctx.actions.args()
    args.add("--in", ctx.file.board)
    args.add("--out", ctx.outputs.out)
    args.add("--net", ctx.attr.net)
    args.add_all("--start", ctx.attr.start)
    args.add_all("--end", ctx.attr.end)
    args.add("--project_in", ctx.file.project)
    args.add("--project_out", ctx.outputs.out_project)
    for t in ctx.attr.ignore:
        args.add("--ignore", t)
    ctx.actions.run(
        executable = ctx.executable._spoil,
        arguments = [args],
        inputs = [ctx.file.board, ctx.file.project],
        outputs = [ctx.outputs.out, ctx.outputs.out_project],
        mnemonic = "SpoilPcb",
        progress_message = "Spoiling %{label} for a known-bad test",
    )
    return [DefaultInfo(files = depset([ctx.outputs.out, ctx.outputs.out_project]))]

spoiled_pcb = rule(
    implementation = _spoiled_pcb_impl,
    doc = "A routed board with one more track, F.Cu, 0.2 mm, on net, for a known-bad test.",
    attrs = {
        "board": attr.label(doc = "The routed board.", allow_single_file = [".kicad_pcb"], mandatory = True),
        "net": attr.string(doc = "The track's net.", mandatory = True),
        "start": attr.string_list(doc = "The track's start, [x, y] on KiCad's page, mm.", mandatory = True),
        "end": attr.string_list(doc = "The track's end, [x, y] on KiCad's page, mm.", mandatory = True),
        "project": attr.label(doc = "The board's project.", allow_single_file = [".kicad_pro"], mandatory = True),
        "ignore": attr.string_list(doc = "Violation types the spoiled project ignores: the track's side effects."),
        "out": attr.output(mandatory = True),
        "out_project": attr.output(mandatory = True),
        "_spoil": attr.label(default = ":spoil", executable = True, cfg = "exec"),
    },
)

def _netlist_bom_impl(ctx):
    args = ctx.actions.args()
    args.add("--netlist", ctx.file.netlist)
    args.add("--csv", ctx.outputs.csv)
    args.add("--md", ctx.outputs.md)
    ctx.actions.run(
        executable = ctx.executable._bom,
        arguments = [args],
        inputs = [ctx.file.netlist],
        outputs = [ctx.outputs.csv, ctx.outputs.md],
        mnemonic = "NetlistBom",
        progress_message = "Writing the BOM of %{label}",
    )
    return [
        DefaultInfo(files = depset([ctx.outputs.csv])),
        OutputGroupInfo(md = depset([ctx.outputs.md])),
    ]

netlist_bom = rule(
    implementation = _netlist_bom_impl,
    doc = """The board's BOM from the circuit's netlist, by bom.py: a CSV with
kicad_bom's columns (Refs, Value, Footprint, Qty, DNP, LCSC, MPN,
Manufacturer) for fab_package, and the same as Markdown (output group md).""",
    attrs = {
        "netlist": attr.label(doc = "The circuit's netlist.", allow_single_file = [".net"], mandatory = True),
        "csv": attr.output(mandatory = True),
        "md": attr.output(mandatory = True),
        "_bom": attr.label(default = ":bom_tool", executable = True, cfg = "exec"),
    },
)

def _fab_summary_impl(ctx):
    mech = ctx.actions.declare_file(ctx.label.name + ".mech.json")
    ctx.actions.write(mech, ctx.attr.mech)
    out = ctx.actions.declare_file(ctx.label.name + ".md")
    args = ctx.actions.args()
    args.add("--zip", ctx.file.package)
    args.add("--mech", mech)
    args.add("--bom", ctx.file.bom_md)
    args.add("--out", out)
    ctx.actions.run(
        executable = ctx.executable._summary,
        arguments = [args],
        inputs = [ctx.file.package, mech, ctx.file.bom_md],
        outputs = [out],
        mnemonic = "FabSummary",
        progress_message = "Summarizing %{label}",
    )
    return [DefaultInfo(files = depset([out]))]

fab_summary = rule(
    implementation = _fab_summary_impl,
    doc = "The fab package as Markdown, for people: order settings, files, parts.",
    attrs = {
        "package": attr.label(doc = "The fab_package ZIP.", allow_single_file = [".zip"], mandatory = True),
        "bom_md": attr.label(doc = "The BOM as Markdown.", allow_single_file = [".md"], mandatory = True),
        "mech": attr.string(doc = "mech/mechanics.bzl's numbers, as JSON.", mandatory = True),
        "_summary": attr.label(default = ":summary_tool", executable = True, cfg = "exec"),
    },
)
