package detect_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/detect"
)

func TestDetectCPPTestFramework(t *testing.T) {
	tests := []struct {
		name     string
		content  string
		expected string
	}{
		{
			name:     "Catch2 v3 find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(Catch2 3 REQUIRED)\ntarget_link_libraries(mytest PRIVATE Catch2::Catch2WithMain)",
			expected: "catch2",
		},
		{
			name:     "GoogleTest find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(GTest REQUIRED)\ntarget_link_libraries(mytest PRIVATE GTest::gtest_main)",
			expected: "gtest",
		},
		{
			name:     "doctest find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(doctest REQUIRED)\ntarget_link_libraries(mytest PRIVATE doctest::doctest)",
			expected: "doctest",
		},
		{
			name:     "Boost.Test find_package",
			content:  "cmake_minimum_required(VERSION 3.20)\nfind_package(Boost REQUIRED COMPONENTS unit_test_framework)\n",
			expected: "boost.test",
		},
		{
			name:     "No test framework",
			content:  "cmake_minimum_required(VERSION 3.20)\nadd_executable(app main.cpp)",
			expected: "",
		},
		{
			name:     "Missing CMakeLists.txt",
			content:  "",
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			if tt.name != "Missing CMakeLists.txt" {
				if err := os.WriteFile(filepath.Join(dir, "CMakeLists.txt"), []byte(tt.content), 0644); err != nil {
					t.Fatal(err)
				}
			}
			got := detect.DetectCPPTestFramework(dir)
			if got != tt.expected {
				t.Fatalf("expected %q, got %q", tt.expected, got)
			}
		})
	}
}
