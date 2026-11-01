# SPDX-License-Identifier: Apache-2.0
"""step_of: a cad_part's STEP file alone, for a rule that takes one STEP file
(cam_job's part). It runs no action."""

load("@hdlf_rules_brep//brep:defs.bzl", "CadPartInfo")

def _step_of_impl(ctx):
    return [DefaultInfo(files = depset([ctx.attr.part[CadPartInfo].step]))]

step_of = rule(
    implementation = _step_of_impl,
    doc = "The STEP file of a cad_part.",
    attrs = {"part": attr.label(mandatory = True, providers = [CadPartInfo])},
)
