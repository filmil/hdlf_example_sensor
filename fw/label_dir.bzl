# SPDX-License-Identifier: Apache-2.0
"""label_dir: a file's directory, from the execution root, for a linker's
-L. It is under external/ when the file's module is not the root module,
as when bazel-cad-book depends on this one, so package_name() alone is
not enough."""

def label_dir(label):
    """The directory of the file `label` names, relative to the execution root.

    Args:
      label: the label of a source file, as a string. It is read in this
        module's repository, wherever the BUILD file that calls this is.

    Returns:
      The directory, such as "fw" or "external/<repo>/src/chips/<chip>".
    """
    label = Label(label)
    parts = [label.workspace_root, label.package, label.name.rpartition("/")[0]]
    return "/".join([p for p in parts if p])
