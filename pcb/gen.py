# SPDX-License-Identifier: Apache-2.0
"""The sensor board's PCB generator.

    gen.py --mech mech.json --netlist netlist.net --footprints DIR \\
        --pcb sensor.kicad_pcb --pro sensor.kicad_pro [--bad missing_net|short]

It writes the PCB from three sources, so that none is copied:

* mech.json: mech/mechanics.bzl's numbers (the board's size and holes,
  where the USB-C receptacle, the LED and the sensor are), which the
  BUILD file passes.
* netlist.net: the circuit, //elec:netlist. Each part's footprint, value
  and fields come from it, and each pad's net; each footprint names its
  component's time stamp, so the PCB and the netlist pair up.
* DIR: KiCad 9.0.9's footprint libraries. Each footprint is placed as the
  library has it.

The placement is placement.py's table. The board has no copper: the
BUILD file routes it with hdlf_rules_kicad's kicad_autoroute (Freerouting).
"""

import argparse
import hashlib
import json
import math
import os
import sys

import placement
import sexpr
from sexpr import A, L, Q

# Where the board's lower-left corner sits on KiCad's page, mm. KiCad's Y
# grows downwards; the board's frame (mechanics.bzl) has Y up.
ORIGIN_X, ORIGIN_Y = 100.0, 100.0


class Board:
    def __init__(self, mech, seed):
        self.mech = mech
        self.width = mech["BOARD"]["width"]
        self.seed = seed
        self.n = 0
        self.items = []
        self.nets = [""]

    def uuid(self):
        self.n += 1
        h = hashlib.sha256(("%s %d" % (self.seed, self.n)).encode()).hexdigest()
        return "%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])

    def kx(self, x):
        return ORIGIN_X + x

    def ky(self, y):
        return ORIGIN_Y + self.width - y

    def net(self, name):
        if name not in self.nets:
            self.nets.append(name)
        return self.nets.index(name)


def num(v):
    v = round(v, 4) + 0.0
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def local_to_board(x0, y0, rot, lx, ly):
    """A footprint's local point (KiCad's axes) on the board (Y up)."""
    t = math.radians(rot)
    kx = lx * math.cos(t) + ly * math.sin(t)
    ky = -lx * math.sin(t) + ly * math.cos(t)
    return x0 + kx, y0 - ky


def read_netlist(path):
    root = sexpr.parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in root.child("components").children("comp"):
        fields = {}
        f = c.child("fields")
        if f:
            for fl in f.children("field"):
                fields[fl.child("name").arg(0)] = fl.arg(0)
        comps[c.child("ref").arg(0)] = {
            "value": c.child("value").arg(0),
            "footprint": c.child("footprint").arg(0),
            "tstamp": c.child("tstamps").arg(0),
            "fields": fields,
        }
    pads = {}
    for n in root.child("nets").children("net"):
        name = n.child("name").arg(0)
        for nd in n.children("node"):
            pads[(nd.child("ref").arg(0), nd.child("pin").arg(0))] = name
    return comps, pads


def footprint(board, libdir, lib_id, ref, value, tstamp, fields, x, y, rot, pad_nets, attrs=()):
    """The library footprint lib_id, placed at board (x, y), rotated rot."""
    lib, name = lib_id.split(":", 1)
    path = os.path.join(libdir, lib + ".pretty", name + ".kicad_mod")
    fp = sexpr.parse(open(path, encoding="utf-8").read())
    keep = [A("footprint"), Q(lib_id)]
    props, rest = [], []
    for c in fp.items[2:]:
        h = c.head()
        if h in ("version", "generator", "generator_version"):
            continue
        if h == "layer":
            keep += [c, L("uuid", Q("")), L("at", A(num(board.kx(x))), A(num(board.ky(y))), A(num(rot)))]
            continue
        if h == "attr":
            for a in attrs:
                if a not in [i.atom for i in c.items[1:]]:
                    c.items.append(A(a))
        if h == "property":
            key = c.arg(0)
            if key == "Reference":
                c.items[2] = Q(ref)
                # The references stay on the fabrication layer: the board
                # is small, and its silkscreen names what a user sees.
                if c.child("hide") is None:
                    c.items.append(L("hide", A("yes")))
            elif key == "Value":
                c.items[2] = Q(value)
            elif key == "Datasheet" and fields.get("Datasheet"):
                c.items[2] = Q(fields["Datasheet"])
            _rotate_at(c, rot)
            props.append(c)
            continue
        if h in ("fp_text",):
            _rotate_at(c, rot)
        if h == "pad":
            _rotate_at(c, rot)
            pn = pad_nets.get(c.arg(0))
            if pn:
                net = L("net", A(str(board.net(pn))), Q(pn))
                idx = next((i for i, e in enumerate(c.items) if e.is_list and e.head() == "uuid"), len(c.items))
                c.items.insert(idx, net)
        rest.append(c)
    for k in sorted(fields):
        if k in ("Datasheet", "Description", "Footprint", "SKiDL Tag", "SKiDL Line"):
            continue
        props.append(L("property", Q(k), Q(fields[k]), L("at", A("0"), A("0"), A(num(rot))),
                       L("layer", Q("F.Fab")), L("hide", A("yes")), L("uuid", Q("")),
                       L("effects", L("font", L("size", A("1"), A("1")), L("thickness", A("0.15"))))))
    out = sexpr.Node(keep + props + ([L("path", Q("/" + tstamp))] if tstamp else []) + rest)
    if not any(c.is_list and c.head() == "attr" for c in out.items) and attrs:
        out.items.insert(len(keep), L("attr", *[A(a) for a in attrs]))
    _fresh(board, out)
    board.items.append(out)
    return fp


def _rotate_at(node, rot):
    at = node.child("at")
    if at is None or rot == 0:
        return
    args = [c for c in at.items[1:] if not c.is_list]
    base = float(args[2].atom) if len(args) > 2 else 0.0
    ang = num((base + rot) % 360)
    if len(args) > 2:
        args[2].atom = ang
    else:
        at.items.append(A(ang))


def _fresh(board, node):
    if node.is_list:
        if node.head() == "uuid" and len(node.items) == 2:
            node.items[1] = Q(board.uuid())
            return
        for c in node.items:
            _fresh(board, c)


def gr_line(board, x1, y1, x2, y2, layer, width=0.05):
    board.items.append(L("gr_line", L("start", A(num(board.kx(x1))), A(num(board.ky(y1)))),
                         L("end", A(num(board.kx(x2))), A(num(board.ky(y2)))),
                         L("stroke", L("width", A(num(width))), L("type", A("solid"))),
                         L("layer", Q(layer)), L("uuid", Q(board.uuid()))))


def gr_arc(board, x1, y1, xm, ym, x2, y2, layer="Edge.Cuts", width=0.05):
    board.items.append(L("gr_arc", L("start", A(num(board.kx(x1))), A(num(board.ky(y1)))),
                         L("mid", A(num(board.kx(xm))), A(num(board.ky(ym)))),
                         L("end", A(num(board.kx(x2))), A(num(board.ky(y2)))),
                         L("stroke", L("width", A(num(width))), L("type", A("solid"))),
                         L("layer", Q(layer)), L("uuid", Q(board.uuid()))))


def slot(board, x1, y1, x2, y2, w):
    """A cut-out slot on Edge.Cuts, w wide, from (x1, y1) to (x2, y2),
    vertical or horizontal, with round ends."""
    r = w / 2
    if x1 == x2:
        lo, hi = min(y1, y2), max(y1, y2)
        gr_line(board, x1 - r, lo, x1 - r, hi, "Edge.Cuts")
        gr_line(board, x1 + r, lo, x1 + r, hi, "Edge.Cuts")
        gr_arc(board, x1 - r, hi, x1, hi + r, x1 + r, hi)
        gr_arc(board, x1 + r, lo, x1, lo - r, x1 - r, lo)
    else:
        lo, hi = min(x1, x2), max(x1, x2)
        gr_line(board, lo, y1 - r, hi, y1 - r, "Edge.Cuts")
        gr_line(board, lo, y1 + r, hi, y1 + r, "Edge.Cuts")
        gr_arc(board, hi, y1 - r, hi + r, y1, hi, y1 + r)
        gr_arc(board, lo, y1 + r, lo - r, y1, lo, y1 - r)


def keepout(board, name, layer, pts):
    """A rule area on layer: no tracks, vias or pours in the polygon pts."""
    board.items.append(L(
        "zone", L("net", A("0")), L("net_name", Q("")), L("layer", Q(layer)),
        L("uuid", Q(board.uuid())), L("name", Q(name)), L("hatch", A("edge"), A("0.5")),
        L("connect_pads", L("clearance", A("0"))), L("min_thickness", A("0.25")),
        L("filled_areas_thickness", A("no")),
        L("keepout", L("tracks", A("not_allowed")), L("vias", A("not_allowed")),
          L("pads", A("allowed")), L("copperpour", A("not_allowed")), L("footprints", A("allowed"))),
        L("placement", L("enabled", A("no")), L("sheetname", Q(""))),
        L("fill", L("thermal_gap", A("0.5")), L("thermal_bridge_width", A("0.5"))),
        L("polygon", L("pts", *[L("xy", A(num(board.kx(x))), A(num(board.ky(y)))) for x, y in pts])),
    ))


LAYERS = """	(layers
		(0 "F.Cu" signal)
		(2 "B.Cu" signal)
		(9 "F.Adhes" user "F.Adhesive")
		(11 "B.Adhes" user "B.Adhesive")
		(13 "F.Paste" user)
		(15 "B.Paste" user)
		(5 "F.SilkS" user "F.Silkscreen")
		(7 "B.SilkS" user "B.Silkscreen")
		(1 "F.Mask" user)
		(3 "B.Mask" user)
		(17 "Dwgs.User" user "User.Drawings")
		(19 "Cmts.User" user "User.Comments")
		(25 "Edge.Cuts" user)
		(27 "Margin" user)
		(31 "F.CrtYd" user "F.Courtyard")
		(29 "B.CrtYd" user "B.Courtyard")
		(35 "F.Fab" user)
		(33 "B.Fab" user)
	)
"""


def project(name):
    """The .kicad_pro: the board's own minimums are zero, so the vendor's
    rules alone decide."""
    return json.dumps({
        "board": {"design_settings": {"rules": {
            "min_clearance": 0.0, "min_track_width": 0.0, "min_via_diameter": 0.0,
            "min_via_annular_width": 0.0, "min_through_hole_diameter": 0.0,
            "min_hole_clearance": 0.0, "min_hole_to_hole": 0.0, "min_copper_edge_clearance": 0.0,
            "min_silk_clearance": 0.0, "min_text_height": 0.0, "min_text_thickness": 0.0,
            "min_connection": 0.0, "min_groove_width": 0.0, "min_microvia_diameter": 0.0,
            "min_microvia_drill": 0.0, "solder_mask_to_copper_clearance": 0.0}}},
        "meta": {"filename": name + ".kicad_pro", "version": 3},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.0, "track_width": 0.2,
                                      "via_diameter": 0.6, "via_drill": 0.3, "priority": 2147483647}],
                         "meta": {"version": 4}},
    }, indent=2, sort_keys=True) + "\n"


# The known-bad PCBs, for netlist_parity_test: each spoils one pad's net.
# missing_net: the sensor's SDA pad is on no net. short: its SCL pad is on
# the SDA net, so that one board net joins two of the netlist's.
BAD = {
    "missing_net": (("U3", "1"), None),
    "short": (("U3", "6"), "I2C_SDA"),
}


def build(mech, comps, pads, libdir, bad):
    board = Board(mech, "hdlf_example_sensor pcb")
    B = mech["BOARD"]
    length, width = B["length"], B["width"]
    gr_line(board, 0, 0, length, 0, "Edge.Cuts")
    gr_line(board, length, 0, length, width, "Edge.Cuts")
    gr_line(board, length, width, 0, width, "Edge.Cuts")
    gr_line(board, 0, width, 0, 0, "Edge.Cuts")

    pads = dict(pads)
    if bad:
        key, net = BAD[bad]
        if key not in pads:
            raise SystemExit("bad %s: no pad %s.%s in the netlist" % (bad, key[0], key[1]))
        if net is None:
            del pads[key]
        else:
            pads[key] = net

    # The parts, where the table puts them, each with its pads' nets.
    placed = {}
    for ref, (x, y, rot) in sorted(placement.positions(mech).items()):
        c = comps.get(ref)
        if c is None:
            raise SystemExit("placement: %s is in no netlist component" % ref)
        pad_nets = {pin: net for (r, pin), net in pads.items() if r == ref}
        attrs = []
        if c["fields"].get("DNP"):
            attrs.append("dnp")
        if c["fields"].get("Exclude from BOM"):
            attrs.append("exclude_from_bom")
        fp = footprint(board, libdir, c["footprint"], ref, c["value"], c["tstamp"], c["fields"],
                       x, y, rot, pad_nets, attrs)
        placed[ref] = (fp, x, y, rot)
    missing = sorted(set(comps) - set(placed))
    if missing:
        raise SystemExit("placement: no place for %s" % ", ".join(missing))

    # The mounting holes: board-only footprints, in no netlist. No copper
    # under a screw head, on either side: a 16-sided keep-out around each.
    r = placement.SCREW_HEAD_KEEPOUT_R / math.cos(math.pi / 16)  # the circle inside it
    for i, (hx, hy) in enumerate(mech["holes"]):
        footprint(board, libdir, placement.HOLE_FOOTPRINT, "H%d" % (i + 1), "M2.5", None, {},
                  hx, hy, 0, {}, ("board_only", "exclude_from_pos_files", "exclude_from_bom"))
        pts = [(hx + r * math.cos(2 * math.pi * k / 16), hy + r * math.sin(2 * math.pi * k / 16)) for k in range(16)]
        for layer in ("F.Cu", "B.Cu"):
            keepout(board, "H%d screw head %s" % (i + 1, layer), layer, pts)

    # No copper under the sensor (TI SNAS678C, section 11.2): no track or
    # via between its pad rows on the top, nor under it on the bottom.
    for name, layer, hx, hy in placement.keepouts(mech):
        sx, sy = mech["SENSOR"]["x"], mech["SENSOR"]["y"]
        keepout(board, name, layer, [(sx - hx, sy - hy), (sx + hx, sy - hy), (sx + hx, sy + hy), (sx - hx, sy + hy)])

    # The sensor's isolation slot (TI SNAS678C §11.2: "Slots around the
    # device can be used to reduce the thermal mass").
    for s in placement.slots(mech):
        slot(board, *s)


    out = ["(kicad_pcb\n\t(version 20241229)\n\t(generator \"hdlf_example_sensor\")\n\t(generator_version \"9.0\")\n",
           "\t(general\n\t\t(thickness %s)\n\t\t(legacy_teardrops no)\n\t)\n\t(paper \"A4\")\n" % num(B["thickness"]),
           LAYERS,
           "\t(setup\n\t\t(pad_to_mask_clearance 0)\n\t\t(allow_soldermask_bridges_in_footprints no)\n\t\t(tenting front back)\n\t)\n"]
    for i, n in enumerate(board.nets):
        out.append("\t(net %d %s)\n" % (i, sexpr.write(Q(n))))
    for it in board.items:
        out.append("\t" + sexpr.write(it, 1) + "\n")
    out.append("\t(embedded_fonts no)\n)\n")
    return "".join(out)


def main(argv):
    p = argparse.ArgumentParser(prog="gen")
    p.add_argument("--mech", required=True)
    p.add_argument("--netlist", required=True)
    p.add_argument("--footprints", required=True)
    p.add_argument("--pcb", required=True)
    p.add_argument("--pro", required=True)
    p.add_argument("--bad", default="", choices=["", "missing_net", "short"])
    a = p.parse_args(argv)
    mech = json.load(open(a.mech, encoding="utf-8"))
    comps, pads = read_netlist(a.netlist)
    text = build(mech, comps, pads, a.footprints, a.bad)
    with open(a.pcb, "w", encoding="utf-8") as f:
        f.write(text)
    name = os.path.basename(a.pro)[: -len(".kicad_pro")]
    with open(a.pro, "w", encoding="utf-8") as f:
        f.write(project(name))


if __name__ == "__main__":
    main(sys.argv[1:])
