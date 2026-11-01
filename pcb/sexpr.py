# SPDX-License-Identifier: Apache-2.0
"""A small reader and writer of KiCad's S-expressions."""


class Node:
    """A list (items) or an atom (atom, quoted)."""

    __slots__ = ("items", "atom", "quoted")

    def __init__(self, items=None, atom=None, quoted=False):
        self.items = items
        self.atom = atom
        self.quoted = quoted

    @property
    def is_list(self):
        return self.items is not None

    def head(self):
        if self.is_list and self.items and not self.items[0].is_list:
            return self.items[0].atom
        return None

    def arg(self, i):
        """The i-th atom after the head, or None."""
        k = 0
        for c in self.items[1:]:
            if not c.is_list:
                if k == i:
                    return c.atom
                k += 1
        return None

    def children(self, head):
        return [c for c in self.items if c.is_list and c.head() == head]

    def child(self, head):
        for c in self.items:
            if c.is_list and c.head() == head:
                return c
        return None

    def copy(self):
        if self.is_list:
            return Node([c.copy() for c in self.items])
        return Node(atom=self.atom, quoted=self.quoted)


def A(s):
    return Node(atom=str(s))


def Q(s):
    return Node(atom=str(s), quoted=True)


def L(head, *items):
    return Node([A(head)] + list(items))


def parse(text):
    """The one S-expression in text."""
    pos = [0]
    n = len(text)

    def space():
        while pos[0] < n and text[pos[0]] in " \t\r\n":
            pos[0] += 1

    def node():
        space()
        if pos[0] >= n:
            raise ValueError("unexpected end")
        c = text[pos[0]]
        if c == "(":
            pos[0] += 1
            items = []
            while True:
                space()
                if pos[0] >= n:
                    raise ValueError("unclosed list")
                if text[pos[0]] == ")":
                    pos[0] += 1
                    return Node(items)
                items.append(node())
        if c == ")":
            raise ValueError("unexpected ) at %d" % pos[0])
        if c == '"':
            pos[0] += 1
            out = []
            while pos[0] < n and text[pos[0]] != '"':
                ch = text[pos[0]]
                if ch == "\\" and pos[0] + 1 < n:
                    pos[0] += 1
                    ch = {"n": "\n", "t": "\t"}.get(text[pos[0]], text[pos[0]])
                out.append(ch)
                pos[0] += 1
            if pos[0] >= n:
                raise ValueError("unclosed string")
            pos[0] += 1
            return Node(atom="".join(out), quoted=True)
        start = pos[0]
        while pos[0] < n and text[pos[0]] not in ' \t\r\n()"':
            pos[0] += 1
        return Node(atom=text[start:pos[0]])

    root = node()
    space()
    if pos[0] != n:
        raise ValueError("text after the top list")
    return root


def _atom(nd):
    if nd.quoted:
        return '"' + nd.atom.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return nd.atom


def write(nd, indent=0):
    """nd as KiCad writes it: nested lists on their own lines, tab-indented."""
    if not nd.is_list:
        return _atom(nd)
    out = ["("]
    nested = False
    for i, c in enumerate(nd.items):
        if c.is_list:
            out.append("\n" + "\t" * (indent + 1) + write(c, indent + 1))
            nested = True
        else:
            if i > 0:
                out.append(" ")
            out.append(_atom(c))
    if nested:
        out.append("\n" + "\t" * indent)
    out.append(")")
    return "".join(out)
