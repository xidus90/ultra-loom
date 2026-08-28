// Command ultraloom-init installs the enforcement of one project.
//
// Everything it decides lives under internal/; this file is only the edge:
// flags in, exit code out. A hook that cannot be tested without a process
// is a hook nobody tests.
package main

import (
	"flag"
	"fmt"
	"os"
)

const version = "0.1.0"

func main() {
	showVersion := flag.Bool("version", false, "print the version and exit")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		os.Exit(0)
	}
	fmt.Fprintln(os.Stderr, "not implemented yet")
	os.Exit(1)
}
