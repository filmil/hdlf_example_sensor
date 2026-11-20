# SPDX-License-Identifier: Apache-2.0
"""Every crate of Cargo.lock has its directory here, and only those, each
as bazel run //tools/crate_licences writes it (tools/crate_licences/check.py)."""

import os
import sys

from tools.crate_licences import check


def main():
    lock = open(os.environ["CARGO_LOCK"]).read()
    readme = open(os.environ["README"]).read()
    problems = check.check(os.path.dirname(os.environ["CARGO_LOCK"]), lock, readme)
    if problems:
        sys.stderr.write("run `bazel run //tools/crate_licences`:\n  " + "\n  ".join(problems) + "\n")
        return 1
    print("%d crates, each with its licence directory" % len(check.locked(lock)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
