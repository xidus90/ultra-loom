package detect

import (
	"os"
	"path/filepath"
	"strings"
)

// DetectCPPTestFramework inspects CMakeLists.txt and package files for known test frameworks.
func DetectCPPTestFramework(root string) string {
	cmakePath := filepath.Join(root, "CMakeLists.txt")
	data, err := os.ReadFile(cmakePath)
	if err != nil {
		return ""
	}
	content := string(data)

	// Check Catch2
	if strings.Contains(content, "Catch2") || strings.Contains(content, "catch2") {
		return "catch2"
	}
	// Check GoogleTest
	if strings.Contains(content, "GTest") || strings.Contains(content, "gtest") || strings.Contains(content, "GoogleTest") {
		return "gtest"
	}
	// Check doctest
	if strings.Contains(content, "doctest") {
		return "doctest"
	}
	// Check Boost.Test / Boost.UT
	if strings.Contains(content, "unit_test_framework") || strings.Contains(content, "boost::ut") {
		return "boost.test"
	}

	return ""
}
