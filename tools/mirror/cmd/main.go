// SPDX-License-Identifier: Apache-2.0

// Command mirror checks the prebuilt archives of tools/mirror/manifest.json
// and, for the operator, uploads them as release assets.
//
// Check every upstream file (what agents run; this is the default):
//
//	bazel run //tools/mirror
//
// Upload (the operator only; it needs gh, logged in with write access):
//
//	bazel run //tools/mirror -- --dry_run=false --release=TAG --built_dir=/path/to/built
//
// --built_dir holds one release's built assets by name, made as the
// manifest's "script" field says, so it needs --release. An upstream file found there by name (a mirrored
// asset's name, or the file name of a built asset's source URL) is used
// instead of downloading it, checked against the same sha256: the build
// leaves its sources there, and SourceForge refuses this tool's
// downloads. Each command is printed before it runs. An upload stops
// before running any command if a file does not match the manifest, in
// any release. gh refuses to replace an asset that
// is already in the release.
//
// Publish to bt.hdlfactory.com (the operator only), each release that
// names a bt base: its checked files, each with a .torrent. The password
// is the Secret bt/bt-upload's; set it in your own shell, and this tool
// reads it from $BT_UPLOAD_PASSWORD only for --to=bt --dry_run=false. It
// never prints it, and a dry run does not need it:
//
//	IFS= read -r BT_UPLOAD_PASSWORD < <(kubectl -n bt get secret bt-upload -o jsonpath='{.data.password}' | base64 -d; echo)
//	export BT_UPLOAD_PASSWORD
//	bazel run //tools/mirror -- --to=bt --dry_run=false --release=TAG [--built_dir=...]
//	unset BT_UPLOAD_PASSWORD
//
// A file already on bt with the same bytes is skipped; one with other
// bytes stops the run before anything is uploaded, in any release.
// (read is a shell builtin, so the password is in no command line; IFS=
// keeps its spaces; echo gives read the newline the secret lacks.)
package main

import (
	"bytes"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/filmil/hdlf_example_sensor/tools/mirror"
)

func run() error {
	root := flag.String("root", os.Getenv("BUILD_WORKSPACE_DIRECTORY"),
		"repository root (default: the workspace of `bazel run`)")
	manifestPath := flag.String("manifest", "tools/mirror/manifest.json", "the manifest, absolute or relative to --root")
	dryRun := flag.Bool("dry_run", true, "check the files only; --dry_run=false uploads them")
	builtDir := flag.String("built_dir", "", "a directory with the built assets, by name; upstream files found there by name are not downloaded")
	release := flag.String("release", "", "only this release tag (default: all)")
	workDir := flag.String("work_dir", "", "where to download (default: a new temporary directory)")
	to := flag.String("to", "github", "where to upload: github (release assets) or bt (bt.hdlfactory.com, with $BT_UPLOAD_PASSWORD)")
	flag.Parse()
	path := *manifestPath
	if !filepath.IsAbs(path) {
		if *root == "" {
			return fmt.Errorf("no root; run it with `bazel run //tools/mirror` or pass --root")
		}
		path = filepath.Join(*root, path)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	m, err := mirror.Parse(b)
	if err != nil {
		return err
	}
	if *builtDir != "" && *release == "" {
		// One build's directory holds one release's files; another release
		// may have a file of the same name with other bytes.
		return fmt.Errorf("--built_dir needs --release")
	}
	if *workDir == "" {
		d, err := os.MkdirTemp("", "mirror-")
		if err != nil {
			return err
		}
		defer os.RemoveAll(d)
		*workDir = d
	}
	// The password, for a real upload to bt only; never printed.
	password := ""
	if *to == "bt" && !*dryRun {
		password = os.Getenv("BT_UPLOAD_PASSWORD")
		if password == "" {
			return fmt.Errorf("--to=bt --dry_run=false needs $BT_UPLOAD_PASSWORD, the Secret bt/bt-upload's password, set in your shell; nothing checked or uploaded")
		}
	}
	return mirror.Mirror(m, mirror.MirrorOptions{
		Options: mirror.Options{
			Client:   &http.Client{Timeout: 30 * time.Minute},
			WorkDir:  *workDir,
			BuiltDir: *builtDir,
			Log:      os.Stdout,
		},
		DryRun:     *dryRun,
		Release:    *release,
		Run:        runCommand,
		To:         *to,
		BtPassword: password,
	})
}

// runCommand prints argv, runs it, and returns its stderr as well as
// showing it.
func runCommand(argv []string) (string, error) {
	fmt.Println("running:", mirror.Quote(argv))
	var stderr bytes.Buffer
	c := exec.Command(argv[0], argv[1:]...)
	c.Stdout = os.Stdout
	c.Stderr = io.MultiWriter(os.Stderr, &stderr)
	err := c.Run()
	return stderr.String(), err
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "mirror:", err)
		os.Exit(1)
	}
}
