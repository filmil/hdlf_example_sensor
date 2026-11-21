# SPDX-License-Identifier: Apache-2.0
"""svg_norm IN OUT: copies a KiCad SVG plot without the date KiCad writes
into its <title> ("... date 2026/11/21 06:00:00"), so the same board gives
the same bytes. Fails if the title has no date to remove, so a KiCad that
writes it differently is noticed."""

import re
import sys

DATE = re.compile(r"(<title>[^<]*?) date \d{4}/\d\d/\d\d \d\d:\d\d:\d\d")


def normalize(text):
    out, n = DATE.subn(r"\1", text)
    if n != 1:
        raise ValueError("found %d dated <title>, want 1" % n)
    return out


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: svg_norm IN OUT\n")
        return 2
    with open(argv[0], encoding="utf-8") as f:
        text = f.read()
    try:
        out = normalize(text)
    except ValueError as e:
        sys.stderr.write("svg_norm: %s: %s\n" % (argv[0], e))
        return 1
    with open(argv[1], "w", encoding="utf-8") as f:
        f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
