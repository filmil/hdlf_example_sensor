// SPDX-License-Identifier: Apache-2.0

// Command dfu_util builds dfu-util, statically linked with libusb, for
// //fw:flash, in the pinned Ubuntu container. The operator runs it by hand,
// with podman on the host:
//
//	bazel run //tools/dfu_util -- --out=/tmp/dfu-util
//
// --out must be missing or empty; a relative one is taken from the
// directory bazel run was started in. It receives dfu-util, the two source
// tarballs as downloaded, dfu-util-licenses.tar and SHA256SUMS, and stays
// empty if the run fails. The tool fails unless the binary's sha256 is the
// one MODULE.bazel pins. tools/mirror checks and uploads its output. With
// --dry_run it prints the command, the script as a here-document, and runs
// nothing.
package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	dfuutil "github.com/filmil/hdlf_example_sensor/tools/dfu_util"
)

func run() error {
	out := flag.String("out", "", "a missing or empty directory for dfu-util, its sources, its licences and SHA256SUMS (required)")
	jobs := flag.Int("jobs", 4, "parallel compile jobs, and the container's CPUs")
	dry := flag.Bool("dry_run", false, "print the command, with the script as a here-document; run nothing")
	flag.Parse()
	if *jobs < 1 {
		return fmt.Errorf("--jobs must be 1 or more")
	}
	abs, err := dfuutil.ResolveOut(*out, os.Getenv("BUILD_WORKING_DIRECTORY"))
	if err != nil {
		return err
	}
	if *dry {
		ca, err := dfuutil.FindCABundle()
		if err != nil {
			return err
		}
		// The run mounts a copy of it; the dry run names the bundle itself.
		fmt.Print(dfuutil.DryRun(dfuutil.Command(abs, ca, *jobs)))
		return nil
	}
	tmp, err := os.MkdirTemp("", "dfu-util-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp)
	ca, err := dfuutil.CopyCABundle(tmp)
	if err != nil {
		return err
	}
	cmd := dfuutil.Command(abs, ca, *jobs)
	if err := dfuutil.CheckOut(abs); err != nil {
		return err
	}
	if err := os.MkdirAll(abs, 0o755); err != nil {
		return err
	}
	c := exec.Command(cmd[0], cmd[1:]...)
	c.Stdin = strings.NewReader(dfuutil.BuildScript)
	c.Stdout, c.Stderr = os.Stdout, os.Stderr
	if err := c.Run(); err != nil {
		return err
	}
	bin := filepath.Join(abs, "dfu-util")
	if err := dfuutil.VerifyBinary(bin); err != nil {
		return err
	}
	fmt.Printf("ok %s: sha256 %s, as pinned\n", bin, dfuutil.BinarySHA256)
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "dfu_util:", err)
		os.Exit(1)
	}
}
