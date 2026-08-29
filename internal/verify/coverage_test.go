package verify_test

import (
	"testing"

	"github.com/xidus90/ultra-loom/internal/verify"
)

func TestParseGoCoverage(t *testing.T) {
	validOutput := "github.com/foo/bar/a.go:10:\tfn\t100.0%\ntotal:\t(statements)\t98.5%\n"
	pct, err := verify.ParseGoCoverage(validOutput)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if pct != 98.5 {
		t.Fatalf("expected 98.5, got %v", pct)
	}

	invalidOutput := "no total line here"
	if _, err := verify.ParseGoCoverage(invalidOutput); err == nil {
		t.Fatal("expected error on missing total line, got nil")
	}

	unparseablePct := "total:\t(statements)\t98..5%"
	if _, err := verify.ParseGoCoverage(unparseablePct); err == nil {
		t.Fatal("expected error on unparseable percentage with multiple dots, got nil")
	}
}

func TestCheckCoverageFloor(t *testing.T) {
	if err := verify.CheckCoverageFloor(98.5, 98.0); err != nil {
		t.Fatalf("expected pass for 98.5 >= 98.0, got: %v", err)
	}

	if err := verify.CheckCoverageFloor(98.0, 98.0); err != nil {
		t.Fatalf("expected pass for 98.0 >= 98.0, got: %v", err)
	}

	if err := verify.CheckCoverageFloor(97.9, 98.0); err == nil {
		t.Fatal("expected failure for 97.9 < 98.0, got nil")
	}
}
