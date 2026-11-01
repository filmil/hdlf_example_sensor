<!-- SPDX-License-Identifier: Apache-2.0 -->
# hdlf_example_sensor

A worked example of the [hdlf_rules_*](https://hdlfactory.com) Bazel modules:
a USB-C temperature and humidity sensor, its board, its 3D-printed
enclosure and its milled aluminium front panel, every output built
hermetically by Bazel. [DESIGN.md](DESIGN.md) describes the design.

It is the example of the modules' user manual, and uses each module for
real:

| Module | Here |
|---|---|
| [hdlf_rules_netlist](https://github.com/filmil/bazel_rules_netlist) | the circuit, written as code (SKiDL) |
| [hdlf_rules_kicad](https://github.com/filmil/bazel_rules_kicad) | the board: DRC, fab outputs, STEP, renders |
| [hdlf_rules_fab](https://github.com/filmil/bazel_rules_fab) | the JLCPCB assembly package |
| [hdlf_rules_brep](https://github.com/filmil/bazel_rules_brep) | the enclosure, the lid and the front panel |
| [hdlf_rules_cam](https://github.com/filmil/bazel_rules_cam) | the front panel's G-code |

## Building

Linux x86_64. Nothing but Bazel (bazelisk) needs to be installed:

```sh
bazel test //...
```

The modules come from the filmil registry, which `.bazelrc` names before
the Bazel Central Registry.

## License

Apache License 2.0 (`LICENSE`). The tools and libraries the build downloads
are under their own licenses, listed in each module's README.
