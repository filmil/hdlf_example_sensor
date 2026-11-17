# SPDX-License-Identifier: Apache-2.0
"""Writes the firmware's pin map, pins.rs, from the board's netlist.

    pinmap.py --netlist N --symbols S --metadata M [--metadata M2 ...]
              --spec fw/pins.json --out pins.rs

For each net the spec names, it finds the chip's pin on that net in the
netlist (KiCad netlist, version D), the pin's name in the KiCad symbol
library (a name like "PA9/PA11" is a pin with two ports, the second after
a remap), and what that port can do in stm32-metapac's metadata for the
chip. It fails, naming every problem, if a net is missing, is not on the
chip, or sits on a pin without the function the spec asks for:

    {"gpio": true}                           any port pin;
    {"peripheral": P, "signal": S}           a pin metapac lists for P's S;
    {"pin": NAME, "why": ...}                that pin, for what metapac
                                             does not describe.

pins.rs is a no_std crate: a const per net, with the port, the pin number
and, for a peripheral signal, its alternate function; and
REMAP_PA11_PA12, true when a net needs the remapped pair.
"""

import argparse
import json
import re
import sys


def sexpr(text):
    """Parses an S-expression into nested lists of strings."""
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', text)
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            if len(stack) < 2:
                raise ValueError("unbalanced )")
            done = stack.pop()
            stack[-1].append(done)
        elif t.startswith('"'):
            stack[-1].append(t[1:-1].replace('\\"', '"'))
        else:
            stack[-1].append(t)
    if len(stack) != 1:
        raise ValueError("unbalanced (")
    return stack[0]


def children(node, head):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def child(node, head):
    found = children(node, head)
    return found[0] if found else None


def value(node, head):
    c = child(node, head)
    return c[1] if c and len(c) > 1 else None


def netlist_nets(text, ref):
    """{net name: [pin number of ref on it]} from a KiCad netlist."""
    root = sexpr(text)
    export = root[0] if root and isinstance(root[0], list) else root
    nets = child(export, "nets")
    if nets is None:
        raise ValueError("the netlist has no (nets)")
    out = {}
    for net in children(nets, "net"):
        name = value(net, "name")
        pins = [value(n, "pin") for n in children(net, "node") if value(n, "ref") == ref]
        out[name] = pins
    return out


def symbol_pins(text, symbol):
    """{pin number: pin name} of a symbol in a KiCad symbol library."""
    root = sexpr(text)
    lib = root[0]
    for sym in children(lib, "symbol"):
        if sym[1] != symbol:
            continue
        if child(sym, "extends") is not None:
            raise ValueError("symbol %s extends another; not supported" % symbol)
        out = {}

        def walk(node):
            for c in node[1:]:
                if isinstance(c, list) and c and c[0] == "pin":
                    out[value(c, "number")] = value(c, "name")
                elif isinstance(c, list) and c and c[0] == "symbol":
                    walk(c)

        walk(sym)
        return out
    raise ValueError("no symbol %s in the library" % symbol)


def metadata(texts):
    """The chip's port pins, and {(peripheral, signal): {pin: af}}."""
    text = "\n".join(texts)
    m = re.search(r"static PINS: &\[Pin\] = &\[(.*?)\];", text, re.S)
    if not m:
        raise ValueError("no PINS table in the metadata")
    ports = set(re.findall(r'Pin \{ name: "(P[A-Z]\d+)" \}', m.group(1)))
    signals = {}
    for p in re.finditer(r'\n    Peripheral \{\n        name: "(\w+)",(.*?)\n    \},', text, re.S):
        for pin, sig, af in re.findall(r'pin: "(\w+)",\s*signal: "(\w+)",\s*af: (?:Some\((\d+)\)|None)', p.group(2)):
            signals.setdefault((p.group(1), sig), {})[pin] = int(af) if af else None
    if not ports or not signals:
        raise ValueError("the metadata has no pins or no peripheral signals")
    return ports, signals


def _resolve_with(spec, nets, names, ports, signals, remap):
    """resolve() for one setting of the PA11/PA12 remap: a pin with two
    names ("PA9/PA11") is its first port without the remap, its second
    with it."""
    ref = spec["chip_ref"]
    chosen, problems = {}, []
    for net, want in sorted(spec["nets"].items()):
        if net not in nets:
            problems.append("%s: no such net in the netlist" % net)
            continue
        pins = nets[net]
        if len(pins) != 1:
            problems.append("%s: on %d pins of %s (%s), want 1" % (net, len(pins), ref, ", ".join(pins) or "none"))
            continue
        name = names.get(pins[0])
        if name is None:
            problems.append("%s: %s pin %s is not in the symbol" % (net, ref, pins[0]))
            continue
        alts = name.split("/")
        alt = remap if len(alts) > 1 else 0
        if alt >= len(alts):
            problems.append("%s: %s pin %s (%s) has no remapped port" % (net, ref, pins[0], name))
            continue
        port = alts[alt]
        if "pin" in want:
            fits, af = port == want["pin"], None
            what = want["pin"]
        elif want.get("gpio"):
            fits, af = port in ports, None
            what = "a port pin"
        else:
            table = signals.get((want["peripheral"], want["signal"]), {})
            fits, af = port in table, table.get(port)
            what = "%s %s" % (want["peripheral"], want["signal"])
        if not fits:
            problems.append("%s: on %s pin %s (%s), which is not %s" % (net, ref, pins[0], port, what))
            continue
        chosen[net] = (port, af, alt)
    return chosen, problems


def resolve(spec, nets, names, ports, signals):
    """Returns ({net: (port, af or None, remap)}, [problem]).

    The PA11/PA12 remap is one setting for the whole chip, so the board must
    fit with it off or with it on. Off is preferred when both fit.
    """
    off = _resolve_with(spec, nets, names, ports, signals, 0)
    if not off[1]:
        return off
    on = _resolve_with(spec, nets, names, ports, signals, 1)
    if not on[1]:
        return on
    # When one setting's problems are part of the other's, the remap is not
    # what is wrong: report the fewer. Both, only when the remap splits them.
    if set(on[1]) <= set(off[1]):
        return {}, on[1]
    if set(off[1]) <= set(on[1]):
        return {}, off[1]
    return {}, (
        ["no setting of the PA11/PA12 remap fits; without it:"]
        + ["  " + p for p in off[1]]
        + ["with it:"]
        + ["  " + p for p in on[1]]
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
    for net, (port, af, alt) in sorted(chosen.items()):
        pin = "Pin { port: '%s', number: %d }" % (port[1], int(port[2:]))
        if alt == 1:
            remap = True
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


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--metadata", action="append", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    spec = json.load(open(a.spec))
    chosen, problems = resolve(
        spec,
        netlist_nets(open(a.netlist).read(), spec["chip_ref"]),
        symbol_pins(open(a.symbols).read(), spec["symbol"]),
        *metadata([open(m).read() for m in a.metadata]),
    )
    if problems:
        sys.stderr.write("pinmap: the netlist does not fit the firmware:\n  " + "\n  ".join(problems) + "\n")
        return 1
    with open(a.out, "w") as f:
        f.write(rust(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
