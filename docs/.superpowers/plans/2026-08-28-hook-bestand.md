# Hook-Bestand (P2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the installer to generate direct, stack-specific tool commands in `.claude/settings.json` that run in parallel rather than wrapping them under a monolithic `ultraloom hook post-edit`.

**Architecture:** Extend `internal/settings` and `cmd/init/run.go` to support multiple stack-specific hook entries per event. Detect stacks (Python, Godot, C#, TypeScript, Rust, Go) and generate direct parallel hooks for formatters, linters, typecheckers, policy guard, and the stop gate.

**Tech Stack:** Go 1.24, JSON merge, Claude Code Hook Schema.

**Spec:** [docs/.superpowers/specs/2026-08-28-hook-bestand-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-28-hook-bestand-design.md)

---

### Task 1: Extend `internal/settings` to Support Multiple Owned Entries per Event/Matcher

**Files:**
- Modify: `internal/settings/merge.go`
- Test: `internal/settings/merge_test.go`

**Interfaces:**
- Consumes: `settings.Entry`
- Produces: `settings.Merge(existing []byte, wanted []Entry) (Result, error)` supporting multiple entries per event with distinct commands.

- [ ] **Step 1: Write test for merging multiple owned entries under same event**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Update `merge.go` to match entries by command/matcher/owner**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

---

### Task 2: Implement Stack-Specific Direct Post-Edit Hooks in `cmd/init`

**Files:**
- Modify: `cmd/init/run.go`
- Test: `cmd/init/run_test.go`

**Interfaces:**
- Consumes: `detect.Facts.Stacks`, `settings.Entry`
- Produces: `hookEntries(facts detect.Facts, wikiHooks bool) []settings.Entry` generating direct tool entries for Python (`ruff`, `dmypy`), Godot (`gdlint`), C# (`dotnet format`, `dotnet build`), TS (`eslint`, `tsc`), Rust (`clippy`, `fmt`), Go (`go vet`).

- [ ] **Step 1: Write unit tests for `hookEntries` covering each stack**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement stack-specific hook generation in `cmd/init/run.go`**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

---

### Task 3: Full Gate & End-to-End Verification in Space Worktree

**Files:**
- Test: `uv run ultraloom check all`
- Test: Run `ulinit.exe` against `.worktrees/test-installer` in `space` repo and inspect generated `.claude/settings.json`.

- [ ] **Step 1: Run full gate `uv run ultraloom check all`**
- [ ] **Step 2: Build `ulinit.exe` and test against `space` worktree**
- [ ] **Step 3: Verify `.claude/settings.json` contains parallel direct tool entries**
- [ ] **Step 4: Commit and finalize**
