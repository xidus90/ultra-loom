// Command ultraloom-init installs the enforcement of one project.
//
// Everything it decides lives under internal/; this file is only the edge:
// flags in, exit code out. A hook that cannot be tested without a process
// is a hook nobody tests.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/xidus90/ultra-loom/internal/detect"
)

const version = "0.1.0"

func main() {
	showVersion := flag.Bool("version", false, "print the version and exit")
	detectOnly := flag.Bool("detect-only", false, "print the detected facts as JSON and exit")
	root := flag.String("root", ".", "the project directory to read")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		os.Exit(0)
	}
	if *detectOnly {
		// Detection writes nothing, so this path is the whole of --dry-run
		// for the part of init that has been built.
		facts := detect.Detect(os.DirFS(*root))
		report, err := json.MarshalIndent(facts, "", "  ")
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println(string(report))
		os.Exit(0)
	}
	fmt.Fprintln(os.Stderr, "not implemented yet")
	os.Exit(1)
}
