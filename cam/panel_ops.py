# SPDX-License-Identifier: Apache-2.0
"""The front panel's operations, with one 2 mm single-flute end mill in 2 mm
aluminium:

1. clear the label's recess;
2. mill the screw and LED holes with a helix, so the tool enters them
   without a plunge (FreeCAD splits their 2.2 mm into 5 turns, 0.44 mm
   each);
3. cut the outline through, 0.2 mm into the spoilboard, with holding tabs,
   so the panel stays in the plate until a person cuts it free.

Feeds are for a hobby router in 6061 aluminium: 18000 rpm, 400 mm/min
across, 100 mm/min down, 0.5 mm per pass. The label's two 0.15 mm passes
and the outline's 0.5 mm passes still enter with a straight plunge (the
outline's in the waste outside the panel): FreeCAD 1.1 has no ramp entry
dressup. tools.json caps every pass at 0.6 mm
(max_stepdown), which gcode_check_test enforces.
"""

import FreeCAD
import Path.Dressup.Tags as Tags
import Path.Op.Helix as Helix
import Path.Op.PocketShape as PocketShape
import Path.Op.Profile as Profile


def flat_faces(model, keep):
    """The names of the model's flat, horizontal faces whose height passes
    keep(z)."""
    return [
        "Face%d" % (i + 1)
        for i, f in enumerate(model.Shape.Faces)
        if f.BoundBox.ZLength < 1e-6 and keep(f.BoundBox.ZMin)
    ]


def put(op, prop, value):
    """Sets a depth property. FinalDepth and StepDown follow expressions
    (the base face's height; the tool's diameter, from the setup sheet), and
    a plain assignment loses to them on the next recompute: a StepDown so set
    leaves the cut in passes as deep as the tool is wide. Clear the
    expression first."""
    op.setExpression(prop, None)
    setattr(op, prop, value)


def through(op, bottom):
    """Cuts op to 0.2 mm below the plate, in 0.5 mm passes."""
    put(op, "StepDown", "0.5 mm")
    put(op, "FinalDepth", bottom - 0.2)


def operations(job, model, tools):
    t1 = tools[1]
    t1.HorizFeed = "400 mm/min"
    t1.VertFeed = "100 mm/min"
    t1.SpindleSpeed = 18000

    top = model.Shape.BoundBox.ZMax
    bottom = model.Shape.BoundBox.ZMin
    inside = lambda z: bottom + 1e-6 < z < top - 1e-6

    # 1. The label's recess: its floor is the only flat face between the
    #    panel's bottom and top, whatever its depth.
    label = PocketShape.Create("Label", parentJob=job)
    label.ToolController = t1
    label.Base = [(model, flat_faces(model, inside))]
    put(label, "StepDown", "0.15 mm")

    # The top face: a profile cuts from its base face down, so it must be
    # the top one (from the bottom face, it would cut the plate in one
    # full-depth pass). Only the outline uses it.
    base = [(model, flat_faces(model, lambda z: abs(z - top) < 1e-6))]

    # 2. The holes, by helix: their walls are the panel's round faces. Helix
    #    leaves each hole with a rapid to its center at full depth, inside
    #    the bore it cut, which gcode_check_test accepts (rules_cam 0.1.0).
    #    The label recess's rounded corners are round faces too, but only
    #    its depth deep; a hole's wall runs the panel's whole thickness.
    walls = [
        "Face%d" % (i + 1)
        for i, f in enumerate(model.Shape.Faces)
        if f.Surface.__class__.__name__ == "Cylinder"
        and abs(abs(f.Surface.Axis.z) - 1) < 1e-6
        and f.BoundBox.ZLength > (top - bottom) - 1e-6
    ]
    # An empty list would cut no holes, silently: fail instead.
    if not walls:
        raise ValueError("the panel has no through holes to mill")
    holes = Helix.Create("Holes", parentJob=job)
    holes.ToolController = t1
    holes.Base = [(model, walls)]
    through(holes, bottom)

    # 3. The outline, with tabs.
    outline = Profile.Create("Outline", parentJob=job)
    outline.ToolController = t1
    outline.Base = base
    outline.processHoles = False
    outline.processCircles = False
    outline.processPerimeter = True
    through(outline, bottom)
    # The tabs are placed along the outline's toolpath, so compute it first.
    FreeCAD.ActiveDocument.recompute()
    tabs = Tags.Create(outline)
    # Four tabs, 3 mm wide and 0.5 mm of metal thick (their height counts
    # from the cut's bottom, 0.2 mm below the plate): a saw or a knife
    # cuts the panel free. FreeCAD's default is half the cut's depth.
    tabs.Width = 3.0
    tabs.Height = 0.7
    # The dressup posts the outline, so the outline must not post again.
    job.Operations.Group = [op for op in job.Operations.Group if op is not outline]
