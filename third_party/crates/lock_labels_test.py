# SPDX-License-Identifier: Apache-2.0
"""cargo-bazel-lock.json names no file of the root module.

rules_rust writes an annotation's labels (such as its patches) into the
lock as "@@//...", the root module's repository. A module that depends on
this one reads that as its own repository, and the fetch fails
(https://github.com/bazelbuild/rules_rust/pull/4425).
"""

import os
import sys


def main():
    path = os.environ["LOCK"]
    with open(path, encoding="utf-8") as f:
        bad = [(n, line.strip()) for n, line in enumerate(f, 1) if '"@@//' in line]
    for n, line in bad:
        print(f"{path}:{n}: names a file of the root module: {line}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
