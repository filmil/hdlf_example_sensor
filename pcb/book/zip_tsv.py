# SPDX-License-Identifier: Apache-2.0
"""zip_tsv ZIP TSV: the files of a fab house's ZIP, for the book's fab
chapter to set as a table: file name, size in bytes, sha256. One row per
file, by name, after a header; the ZIP's own row last, as "(the ZIP)"."""

import hashlib
import os
import sys
import zipfile


def table(path):
    rows = ["file\tsize\tsha256"]
    with zipfile.ZipFile(path) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            data = z.read(info)
            rows.append("%s\t%d\t%s" % (info.filename, len(data), hashlib.sha256(data).hexdigest()))
    with open(path, "rb") as f:
        whole = f.read()
    rows.append("(the ZIP)\t%d\t%s" % (len(whole), hashlib.sha256(whole).hexdigest()))
    return "\n".join(rows) + "\n"


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: zip_tsv ZIP TSV\n")
        return 2
    with open(argv[1], "w", encoding="utf-8") as f:
        f.write(table(argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
