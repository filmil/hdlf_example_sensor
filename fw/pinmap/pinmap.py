# SPDX-License-Identifier: Apache-2.0
"""Writes the firmware's pin map, pins.rs, from the board's netlist.

    pinmap.py --netlist N --symbols LIB.kicad_sym --metadata M [--metadata M ...]
              --spec fw/pins.json --out pins.rs

The spec (fw/pins.json) names the chip's reference (U1), the part it must
be, the stm32-metapac chip, and the nets the firmware uses. For each net,
it finds U1's pin on that net in the netlist (KiCad netlist, version D),
the pin's name in the KiCad symbol the netlist names for U1, and what that
port can do in stm32-metapac's metadata for the chip. A net asks for one
of:

    {"gpio": true}                       any port pin;
    {"peripheral": P, "signal": S}       a pin metapac lists for P's S;
    {"pin": PORT, "why": ...}            that port pin, for what metapac
                                         does not describe.

It fails, naming every problem, if U1 is not the spec's part, if a net is
missing, on no pin or on more than one pin of U1, on a pin without its
function, or on the same pin as another net; and if the metadata is not
the spec's chip or does not parse in full.

Pins 17 and 18 of the STM32F042F6 TSSOP20 are "PA9/PA11" and "PA10/PA12":
the second port after the PA11/PA12 remap (SYSCFG_CFGR1), one setting for
the whole chip. The board must fit with the remap off or with it on.

pins.rs is a no_std crate: a const per net, an AfPin when metapac gives the
signal an alternate function and a Pin otherwise (a GPIO, BOOT0, and USB,
whose pins are analog); and REMAP_PA11_PA12.
"""

import argparse
import json
import os
import re
import sys

# The pins whose name is two ports, switched by the PA11/PA12 remap.
REMAP_PAIRS = {"PA9/PA11", "PA10/PA12"}
PORT = re.compile(r"^P[A-F]\d{1,2}$")


def _unescape(s):
    return re.sub(r"\\(.)", r"\1", s)


def sexpr(text):
    """Parses an S-expression into nested lists of strings."""
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|"|[^\s()"]+', text)
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            if len(stack) < 2:
                raise ValueError("unbalanced )")
            done = stack.pop()
            stack[-1].append(done)
        elif t == '"':
            raise ValueError("a string with no closing quote")
        elif t.startswith('"'):
            stack[-1].append(_unescape(t[1:-1]))
        else:
            stack[-1].append(t)
    if len(stack) != 1:
        raise ValueError("unbalanced (")
    return stack[0]


def _top(text, head):
    root = sexpr(text)
    if len(root) != 1 or not isinstance(root[0], list) or not root[0] or root[0][0] != head:
        raise ValueError("not a (%s ...) file" % head)
    return root[0]


def children(node, head):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def child(node, head):
    found = children(node, head)
    return found[0] if found else None


def value(node, head):
    c = child(node, head)
    return c[1] if c and len(c) > 1 and isinstance(c[1], str) else None


def netlist_part(text, ref):
    """The netlist's component ref: value, lib, symbol and footprint."""
    comps = child(_top(text, "export"), "components")
    if comps is None:
        raise ValueError("the netlist has no (components)")
    found = [c for c in children(comps, "comp") if value(c, "ref") == ref]
    if len(found) != 1:
        raise ValueError("the netlist has %d components %s, want 1" % (len(found), ref))
    c = found[0]
    src = child(c, "libsource")
    return {
        "value": value(c, "value"),
        "lib": value(src, "lib") if src else None,
        "symbol": value(src, "part") if src else None,
        "footprint": value(c, "footprint"),
    }


def netlist_nets(text, ref):
    """{net name: [pin number of ref on it]} from a KiCad netlist."""
    nets = child(_top(text, "export"), "nets")
    if nets is None:
        raise ValueError("the netlist has no (nets)")
    out = {}
    for net in children(nets, "net"):
        out[value(net, "name")] = [value(n, "pin") for n in children(net, "node") if value(n, "ref") == ref]
    return out


def symbol_pins(text, symbol):
    """{pin number: pin name} of a symbol in a KiCad symbol library."""
    lib = _top(text, "kicad_symbol_lib")
    for sym in children(lib, "symbol"):
        if len(sym) < 2 or sym[1] != symbol:
            continue
        if child(sym, "extends") is not None:
            raise ValueError("symbol %s extends another; not supported" % symbol)
        out = {}

        def walk(node):
            for c in node[1:]:
                if isinstance(c, list) and c and c[0] == "pin":
                    n, m = child(c, "number"), child(c, "name")
                    if not n or not m or len(n) < 2 or len(m) < 2:
                        raise ValueError("symbol %s: a pin with no number or name" % symbol)
                    if n[1] in out:
                        raise ValueError("symbol %s: pin %s twice" % (symbol, n[1]))
                    out[n[1]] = m[1]
                elif isinstance(c, list) and c and c[0] == "symbol":
                    walk(c)

        walk(sym)
        if not out:
            raise ValueError("symbol %s has no pins" % symbol)
        return out
    raise ValueError("no symbol %s in the library" % symbol)


def metadata(files, chip):
    """The chip's port pins, and {(peripheral, signal): {pin: af}}.

    files maps path to text. The chip's metadata.rs (chips/<chip>/metadata.rs)
    names the shard it includes; that shard must be among the files.
    """
    suffix = os.path.join("chips", chip.lower(), "metadata.rs")
    mine = [p for p in files if p.endswith(suffix)]
    if len(mine) != 1:
        raise ValueError("want one %s among the metadata, have %d" % (suffix, len(mine)))
    head = files[mine[0]]
    if not re.search(r'\bname: "%s",' % re.escape(chip), head):
        raise ValueError("%s is not the metadata of %s" % (mine[0], chip))
    inc = re.findall(r'include!\("\.\./(metadata_\d+\.rs)"\);', head)
    if len(inc) != 1:
        raise ValueError("%s includes %d shards, want 1" % (mine[0], len(inc)))
    shard = [p for p in files if os.path.basename(p) == inc[0]]
    if len(shard) != 1:
        raise ValueError(
            "%s includes %s, which is not among the metadata files: after an stm32-metapac update, "
            "name it in MODULE.bazel's chip_metadata filegroup" % (mine[0], inc[0]))
    text = files[shard[0]]

    m = re.search(r"static PINS: &\[Pin\] = &\[(.*?)\];", text, re.S)
    if not m:
        raise ValueError("no PINS table in %s" % inc[0])
    ports = re.findall(r'Pin \{ name: "(P[A-Z]\d+)" \}', m.group(1))
    if len(ports) != m.group(1).count("Pin {"):
        raise ValueError("%s: PINS has entries this reader does not parse" % inc[0])
    signals = {}
    blocks = re.findall(r'\n    Peripheral \{\n        name: "(\w+)",(.*?)\n    \},', text, re.S)
    if len(blocks) != len(re.findall(r"\n    Peripheral \{", text)):
        raise ValueError("%s: peripherals this reader does not parse" % inc[0])
    parsed = 0
    for name, body in blocks:
        for pin, sig, af in re.findall(r'pin: "(\w+)",\s*signal: "(\w+)",\s*af: (?:Some\((\d+)\)|None),', body):
            signals.setdefault((name, sig), {})[pin] = int(af) if af else None
            parsed += 1
    if parsed != text.count("PeripheralPin {"):
        raise ValueError("%s: peripheral pins this reader does not parse" % inc[0])
    if not ports or not signals:
        raise ValueError("%s has no pins or no peripheral signals" % inc[0])
    return set(ports), signals


def check_spec(spec):
    """The spec's own problems: each net asks for exactly one valid thing."""
    problems = []
    for k in ("chip_ref", "chip", "part", "nets"):
        if k not in spec:
            problems.append("spec: no %s" % k)
    for net, want in sorted(spec.get("nets", {}).items()):
        if not re.match(r"^[A-Z][A-Z0-9_]*$", net):
            problems.append("spec: %s is not a Rust constant's name" % net)
        keys = set(want)
        if keys == {"gpio"} and want["gpio"] is True:
            continue
        if keys == {"peripheral", "signal"} and all(isinstance(want[k], str) and want[k] for k in keys):
            continue
        if keys == {"pin", "why"} and isinstance(want["pin"], str) and PORT.match(want["pin"]) and want["why"]:
            continue
        problems.append('spec: %s asks for %r; want {"gpio": true}, {"peripheral", "signal"} or {"pin": PORT, "why"}' % (net, want))
    return problems


def _resolve_with(spec, nets, names, ports, signals, remap):
    """resolve() for one setting of the remap. Problems are (net, text)."""
    ref = spec["chip_ref"]
    chosen, problems = {}, []
    for net, want in sorted(spec["nets"].items()):
        if net not in nets:
            problems.append((net, "%s: no such net in the netlist" % net))
            continue
        pins = nets[net]
        if len(pins) != 1:
            problems.append((net, "%s: on %d pins of %s (%s), want 1" % (net, len(pins), ref, ", ".join(pins) or "none")))
            continue
        name = names.get(pins[0])
        if name is None:
            problems.append((net, "%s: %s pin %s is not in the symbol" % (net, ref, pins[0])))
            continue
        if "/" in name and name not in REMAP_PAIRS:
            problems.append((net, "%s: %s pin %s is %s, a two-name pin other than the PA11/PA12 remap" % (net, ref, pins[0], name)))
            continue
        alt = remap if name in REMAP_PAIRS else 0
        port = name.split("/")[alt]
        if "pin" in want:
            fits, af, what = port == want["pin"], None, want["pin"]
        elif want.get("gpio"):
            fits, af, what = port in ports, None, "a port pin"
        else:
            table = signals.get((want["peripheral"], want["signal"]), {})
            fits, af = port in table, table.get(port)
            what = "%s %s" % (want["peripheral"], want["signal"])
        if not fits:
            problems.append((net, "%s: on %s pin %s (%s), which is not %s" % (net, ref, pins[0], port, what)))
            continue
        chosen[net] = (port, af, alt, pins[0])
    by_pin = {}
    for net, c in chosen.items():
        by_pin.setdefault(c[3], []).append(net)
    for pin, on in sorted(by_pin.items()):
        if len(on) > 1:
            problems.append((None, "%s pin %s carries nets %s, which the firmware drives apart" % (ref, pin, ", ".join(sorted(on)))))
    return chosen, problems


def resolve(spec, nets, names, ports, signals):
    """Returns ({net: (port, af or None, remap, pin number)}, [problem]).

    The board must fit with the remap off or on; off when both fit. When
    neither does, the nets that fail one way and not the other are the
    remap's doing: if none, the problems are the board's, reported once.
    """
    off = _resolve_with(spec, nets, names, ports, signals, 0)
    if not off[1]:
        return off[0], []
    on = _resolve_with(spec, nets, names, ports, signals, 1)
    if not on[1]:
        return on[0], []
    off_nets = {n for n, _ in off[1]}
    on_nets = {n for n, _ in on[1]}
    if on_nets < off_nets:
        return {}, [t for _, t in on[1]]
    if off_nets <= on_nets:
        return {}, [t for _, t in off[1]]
    return {}, (
        ["no setting of the PA11/PA12 remap fits; without it:"]
        + ["  " + t for _, t in off[1]]
        + ["with it:"]
        + ["  " + t for _, t in on[1]]
    )


def rust(chosen):
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// Generated by //fw:pins_rs (fw/pinmap/pinmap.py) from //elec:netlist; do not edit.",
        "//! The sensor's MCU pins, by net, from the board's netlist.",
        "#![no_std]",
        "",
        "/// A port pin: its port letter and number, as in PA4.",
        "#[derive(Clone, Copy, Debug, PartialEq, Eq)]",
        "pub struct Pin {",
        "    pub port: char,",
        "    pub number: u8,",
        "}",
        "",
        "/// A pin and the alternate function that connects it to a peripheral.",
        "#[derive(Clone, Copy, Debug, PartialEq, Eq)]",
        "pub struct AfPin {",
        "    pub pin: Pin,",
        "    pub af: u8,",
        "}",
        "",
    ]
    remap = False
    for net, (port, af, alt, _) in sorted(chosen.items()):
        m = re.match(r"^P([A-F])(\d{1,2})$", port)
        if not m:
            raise ValueError("%s: %s is not a port pin" % (net, port))
        pin = "Pin { port: '%s', number: %d }" % (m.group(1), int(m.group(2)))
        remap = remap or alt == 1
        if af is None:
            lines.append("/// Net %s: %s." % (net, port))
            lines.append("pub const %s: Pin = %s;" % (net, pin))
        else:
            lines.append("/// Net %s: %s, alternate function %d." % (net, port, af))
            lines.append("pub const %s: AfPin = AfPin { pin: %s, af: %d };" % (net, pin, af))
        lines.append("")
    lines.append("/// Whether the firmware must remap PA9/PA10 to PA11/PA12 (SYSCFG_CFGR1).")
    lines.append("pub const REMAP_PA11_PA12: bool = %s;" % ("true" if remap else "false"))
    return "\n".join(lines) + "\n"


def tsv(spec, nets, names, chosen):
    """The pinout as a table, for the book: one row per pin of the chip,
    tab-separated, with a header. pin: its number; name: the symbol's
    name for it; net: the board's net on it ("" when none); port: the port
    pin the firmware uses ("" for pins it does not drive); function: what
    pins.json asks of it (gpio, a peripheral signal, or the fixed pin it
    must be); af: the alternate function, when there is one."""
    on_pin = {}
    for net, pins in nets.items():
        if net.startswith("unconnected-"):
            continue
        for p in pins:
            on_pin.setdefault(p, []).append(net)
    used = {c[3]: (net, c) for net, c in chosen.items()}
    rows = ["pin\tname\tnet\tport\tfunction\taf"]
    for pin in sorted(names, key=lambda p: (len(p), p)):
        port = function = af = ""
        if pin in used:
            net, (port, a, _, _) = used[pin]
            want = spec["nets"][net]
            if "pin" in want:
                function = "pin " + want["pin"]
            elif want.get("gpio"):
                function = "gpio"
            else:
                function = "%s %s" % (want["peripheral"], want["signal"])
            af = "" if a is None else str(a)
        rows.append("\t".join([pin, names[pin], ",".join(sorted(on_pin.get(pin, []))), port, function, af]))
    return "\n".join(rows) + "\n"


def run(netlist, symbols, metadata_files, spec, fmt="rust"):
    """Returns (pins.rs text, or the pinout table when fmt is "tsv", or
    None; [problem])."""
    problems = check_spec(spec)
    if problems:
        return None, problems
    ref, part = spec["chip_ref"], spec["part"]
    have = netlist_part(netlist[1], ref)
    for k in ("value", "lib", "symbol", "footprint"):
        if have.get(k) != part.get(k):
            problems.append("%s: its %s is %r in the netlist, the spec wants %r" % (ref, k, have.get(k), part.get(k)))
    lib_file = os.path.basename(symbols[0])
    if lib_file != part["lib"] + ".kicad_sym":
        problems.append("--symbols is %s, the netlist's library is %s" % (lib_file, part["lib"]))
    if problems:
        return None, problems
    nets = netlist_nets(netlist[1], ref)
    names = symbol_pins(symbols[1], part["symbol"])
    chosen, problems = resolve(spec, nets, names, *metadata(metadata_files, spec["chip"]))
    if problems:
        return None, problems
    if fmt == "tsv":
        return tsv(spec, nets, names, chosen), []
    return rust(chosen), []


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--metadata", action="append", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--format", choices=["rust", "tsv"], default="rust",
                    help="rust: pins.rs; tsv: the pinout table, from the same checks")
    a = ap.parse_args(argv)

    def read(p):
        with open(p) as f:
            return f.read()

    try:
        out, problems = run(
            (a.netlist, read(a.netlist)),
            (a.symbols, read(a.symbols)),
            {m: read(m) for m in a.metadata},
            json.loads(read(a.spec)),
            a.format,
        )
    except ValueError as e:
        out, problems = None, [str(e)]
    if problems:
        sys.stderr.write("pinmap: the netlist does not fit the firmware:\n  " + "\n  ".join(problems) + "\n")
        return 1
    with open(a.out, "w") as f:
        f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
