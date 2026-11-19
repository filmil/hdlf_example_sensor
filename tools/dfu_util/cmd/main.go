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
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"

	dfuutil "github.com/filmil/hdlf_example_sensor/tools/dfu_util"
)

func run() error {
	o, err := dfuutil.ParseArgs(os.Args[1:], os.Getenv("BUILD_WORKING_DIRECTORY"))
	if err != nil {
		return err
	}
	bundle, err := dfuutil.FindCABundle()
	if err != nil {
		return err
	}
	if o.Dry {
		// A script that makes, mounts and removes its own CA copy: printing
		// it changes nothing here.
		fmt.Print(dfuutil.DryRun(o.Out, bundle, o.Jobs))
		return nil
	}
	if err := dfuutil.CheckOut(o.Out); err != nil {
		return err
	}
	if err := os.MkdirAll(o.Out, 0o755); err != nil {
		return err
	}
	// The container mounts a copy of the CA bundle, removed after the run;
	// never the host's file, which :Z would relabel.
	tmp, err := os.MkdirTemp("", "dfu-util-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp)
	ca, err := dfuutil.CopyCABundle(tmp)
	if err != nil {
		return err
	}
	if err := dfuutil.CheckMount(ca); err != nil {
		return err
	}
	cmd := dfuutil.Command(o.Out, ca, o.Jobs)
	c := exec.Command(cmd[0], cmd[1:]...)
	c.Stdin = strings.NewReader(dfuutil.BuildScript)
	c.Stdout, c.Stderr = os.Stdout, os.Stderr
	if err := c.Run(); err != nil {
		// build.sh copies to /out last; an interrupted copy may leave part.
		return errors.Join(err, dfuutil.CleanOut(o.Out))
	}
	// On a mismatch this empties --out again: nothing unverified is left.
	if err := dfuutil.VerifyOutput(o.Out); err != nil {
		return err
	}
	fmt.Printf("ok %s: dfu-util has sha256 %s, as pinned, and so do its sources and licences\n", o.Out, dfuutil.BinarySHA256)
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "dfu_util:", err)
		os.Exit(1)
	}
}
