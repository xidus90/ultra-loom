package coverage

import "testing"

func TestFailUnderInPyprojectCounts(t *testing.T) {
	if !Enforced([]byte("[tool.coverage.report]\nfail_under = 100\n"), nil) {
		t.Fatal("fail_under in pyproject was not seen")
	}
}

func TestFailUnderInCoveragercCounts(t *testing.T) {
	if !Enforced(nil, []byte("[report]\nfail_under = 90\n")) {
		t.Fatal("fail_under in .coveragerc was not seen")
	}
}

func TestAThresholdNobodyEnforcesIsNotEnforced(t *testing.T) {
	if Enforced([]byte("[project]\nname = \"x\"\n"), nil) {
		t.Fatal("claimed enforcement where there is none")
	}
}

// A threshold under someone else's table is the false alarm this package
// exists to prevent: coverage.py reads only [tool.coverage.report].
func TestFailUnderUnderAnotherToolIsNotEnforcement(t *testing.T) {
	if Enforced([]byte("[tool.mypy]\nfail_under = 100\n"), nil) {
		t.Fatal("read a foreign table as a coverage threshold")
	}
}

func TestFailUnderInsideAStringIsNotEnforcement(t *testing.T) {
	src := "[tool.ruff]\nhelp = \"\"\"\nfail_under = 100\n\"\"\"\n"
	if Enforced([]byte(src), nil) {
		t.Fatal("read prose inside a string as a coverage threshold")
	}
}

// Dotted keys and inline tables are the same table written differently, and
// coverage.py honours them; a line scanner would not.
func TestDottedKeyCounts(t *testing.T) {
	if !Enforced([]byte("tool.coverage.report.fail_under = 95\n"), nil) {
		t.Fatal("dotted key was not seen")
	}
}

func TestInlineTableCounts(t *testing.T) {
	if !Enforced([]byte("[tool.coverage]\nreport = { fail_under = 80 }\n"), nil) {
		t.Fatal("inline table was not seen")
	}
}

func TestAFloatThresholdCounts(t *testing.T) {
	if !Enforced([]byte("[tool.coverage.report]\nfail_under = 99.5\n"), nil) {
		t.Fatal("float threshold was not seen")
	}
}

func TestBrokenTomlEnforcesNothing(t *testing.T) {
	if Enforced([]byte("[tool.coverage.report\nfail_under = 100\n"), nil) {
		t.Fatal("claimed enforcement from a file no tool can read")
	}
}

// Zero is coverage.py's default and can never fail a run, so writing it out
// says exactly as much as leaving the key away.
func TestZeroInPyprojectEnforcesNothing(t *testing.T) {
	if Enforced([]byte("[tool.coverage.report]\nfail_under = 0\n"), nil) {
		t.Fatal("a threshold of zero was counted as enforcement")
	}
}

func TestZeroInCoveragercEnforcesNothing(t *testing.T) {
	if Enforced(nil, []byte("[report]\nfail_under = 0\n")) {
		t.Fatal("a threshold of zero was counted as enforcement")
	}
}

func TestAThresholdOfTheWrongTypeEnforcesNothing(t *testing.T) {
	if Enforced([]byte("[tool.coverage.report]\nfail_under = \"soon\"\n"), nil) {
		t.Fatal("counted a value coverage.py would refuse")
	}
	if Enforced(nil, []byte("[report]\nfail_under = soon\n")) {
		t.Fatal("counted a value coverage.py would refuse")
	}
}

func TestACommentedThresholdEnforcesNothing(t *testing.T) {
	for _, src := range []string{"[report]\n# fail_under = 100\n", "[report]\n; fail_under = 100\n"} {
		if Enforced(nil, []byte(src)) {
			t.Fatalf("read a comment as a threshold: %q", src)
		}
	}
}

func TestFailUnderInAnotherIniSectionIsNotEnforcement(t *testing.T) {
	if Enforced(nil, []byte("[run]\nfail_under = 100\n")) {
		t.Fatal("read [run] as [report]")
	}
}

// configparser takes a colon for a delimiter, so a file that really does
// enforce must not be called unenforced over one character.
func TestAColonDelimitedThresholdCounts(t *testing.T) {
	if !Enforced(nil, []byte("[report]\nfail_under: 90\n")) {
		t.Fatal("colon delimiter was not seen")
	}
}

func TestAKeyOutsideAnySectionEnforcesNothing(t *testing.T) {
	if Enforced(nil, []byte("fail_under = 100\n")) {
		t.Fatal("read a homeless key as a threshold")
	}
}

func TestBothFilesEmptyEnforceNothing(t *testing.T) {
	if Enforced(nil, nil) {
		t.Fatal("claimed enforcement from nothing at all")
	}
}

func TestOtherKeysInTheReportSectionAreSteppedOver(t *testing.T) {
	if !Enforced(nil, []byte("[report]\nshow_missing = true\nfail_under = 90\n")) {
		t.Fatal("a neighbouring key hid the threshold")
	}
	if Enforced(nil, []byte("[report]\nshow_missing\n")) {
		t.Fatal("read a line without a delimiter as a threshold")
	}
}
