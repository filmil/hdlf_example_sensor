# SPDX-License-Identifier: Apache-2.0
"""The front panel's operations, with one 2 mm single-flute end mill in 2 mm
aluminium: clear the label's recess, then cut the holes and the outline
through, 0.2 mm into the spoilboard.

Feeds are for a hobby router in 6061 aluminium: 18000 rpm, 400 mm/min
across, 100 mm/min down, 0.5 mm per pass.
"""

import Path.Op.PocketShape as PocketShape
import Path.Op.Profile as Profile


def flat_faces(model, z):
    """The names of the model's flat faces at height z."""
    return [
        "Face%d" % (i + 1)
        for i, f in enumerate(model.Shape.Faces)
        if f.BoundBox.ZLength < 1e-6 and abs(f.BoundBox.ZMin - z) < 1e-6
    ]


def operations(job, model, tools):
    t1 = tools[1]
    t1.HorizFeed = "400 mm/min"
    t1.VertFeed = "100 mm/min"
    t1.SpindleSpeed = 18000

    top = model.Shape.BoundBox.ZMax
    bottom = model.Shape.BoundBox.ZMin

    # The label's recess: its floor is the only flat face between the
    # panel's bottom and top.
    floors = [f for f in flat_faces(model, top - 0.3)]
    label = PocketShape.Create("Label", parentJob=job)
    label.ToolController = t1
    label.Base = [(model, floors)]
    label.StepDown = "0.15 mm"

    # The holes and the outline, through. The bottom face's edges are the
    # outline and the holes and nothing else (the label does not go through),
    # and Profile cuts round holes only with processCircles.
    cut = Profile.Create("Through", parentJob=job)
    cut.ToolController = t1
    cut.Base = [(model, flat_faces(model, bottom))]
    cut.processHoles = True
    cut.processCircles = True
    cut.processPerimeter = True
    cut.StepDown = "0.5 mm"
    # FinalDepth follows an expression (the face's height); clear it, or
    # FreeCAD sets it back on the next recompute.
    cut.setExpression("FinalDepth", None)
    cut.FinalDepth = bottom - 0.2
