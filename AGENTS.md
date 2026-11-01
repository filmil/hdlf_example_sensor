<!-- SPDX-License-Identifier: Apache-2.0 -->
# Instructions

Read `README.md` and `DESIGN.md` first.

The coding standard is the `ai-coding-sop` repository at
`https://github.com/filmil/ai-coding-sop`. Its `AGENTS.md`, its
`prose-readability` skill, its `git-commit-rules` skill and its `hermetic`
and `bazel` fragments apply here in full. Where this file and
ai-coding-sop differ, ai-coding-sop wins.

# Rules

1. A change is complete only when `bazel test //...` passes.
2. Keep every action hermetic: the modules' toolchains bring every tool.
   `--action_env=PATH`, `use_default_shell_env = True` and the tags
   `local` and `no-sandbox` are forbidden.
3. Every part is real: an LCSC number, an MPN and a datasheet URL. Invent
   nothing.
4. A change to the board or a part attaches its renders to the pull
   request; a change to the panel's job attaches its G-code check report.
5. One logical change per pull request.
6. Stop and ask the operator before you change a module's version, write
   G-code that a machine will run, or order anything.
