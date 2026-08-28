package main

import "testing"

// The version is the one thing a user can ask for before anything is
// configured, so it is also the first thing that must exist.
func TestVersionIsNotEmpty(t *testing.T) {
	if version == "" {
		t.Fatal("version must not be empty")
	}
}
