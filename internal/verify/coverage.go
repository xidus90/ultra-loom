package verify

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var goCoverTotalRegex = regexp.MustCompile(`(?m)^total:\s+\(statements\)\s+([0-9.]+)%`)

// ParseGoCoverage extracts total statement percentage from `go tool cover -func` output.
func ParseGoCoverage(output string) (float64, error) {
	matches := goCoverTotalRegex.FindStringSubmatch(output)
	if len(matches) < 2 {
		return 0, fmt.Errorf("go tool cover output did not contain total percentage: %s", strings.TrimSpace(output))
	}
	pct, err := strconv.ParseFloat(matches[1], 64)
	if err != nil {
		return 0, fmt.Errorf("parse coverage percentage %q: %w", matches[1], err)
	}
	return pct, nil
}

// CheckCoverageFloor validates that the measured coverage satisfies the minimum floor.
func CheckCoverageFloor(measured, floor float64) error {
	if measured < floor {
		return fmt.Errorf("coverage %.1f%% is below required floor of %.1f%%", measured, floor)
	}
	return nil
}
