# Codebase Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up legacy remnants, dead code, orphaned build artifacts, outdated hook paths, contradictory comments, and language rule violations across UltraLoom.

**Architecture:** Remove dead Go variables/functions and fix error propagation; align `.claude/settings.json` hook paths with current repository architecture; translate German CLI error messages to English (conforming to AGENTS.md); anchor `.gitignore` rules to prevent hiding active source files; purge orphaned cache directories and local test/build artifacts; optionally prune merged git worktrees.

**Tech Stack:** Go (1.27), Python (3.13), Git, TOML, JSON

**Spec:** Referenced in `docs/.superpowers/specs/2026-09-01-audit-nacharbeit-design.md` (on branch `feat/audit-nacharbeit`).

## Global Constraints

- Preserve all existing tests and ensure 100% green suites (`go test ./...`, `uv run pytest`).
- Coverage thresholds remain strict: Python `fail_under = 100`, Go >= 98.0%.
- Respect `AGENTS.md` language rules: English for comments, error messages, and configs; no credits in commit messages.
- TDD discipline: verify each test failure or before/after state when touching code.

---

### Task 1: Fix Dead Code and Swallowed Errors in Go Core

**Files:**
- Modify: `internal/render/render.go`
- Test: `internal/render/render_test.go`
- Modify: `internal/tooling/tooling.go`
- Test: `internal/tooling/tooling_test.go`
- Delete or modify: `internal/detect/cpp_tests.go` & `internal/detect/cpp_tests_test.go`

- [ ] **Step 1: Check unused `var targets` in `internal/render/render.go`**
  Remove `var targets` on line 24. Ensure `go vet ./...` and `go test ./internal/render/...` pass.

- [ ] **Step 2: Propagate template execution error in `one()`**
  In `internal/render/render.go:214`, change `_ = parsed.Execute(&buf, data)` to check and return the error.
  Verify with a failing test case in `render_test.go` (e.g. broken template or unclosed action).

- [ ] **Step 3: Remove unused `ToolSpec.Description` in `internal/tooling/tooling.go`**
  Remove field `Description` from `type ToolSpec` and remove the 14 unused string initializations.
  Ensure `go test ./internal/tooling/...` passes.

- [ ] **Step 4: Clean up `DetectCPPTestFramework` in `internal/detect/cpp_tests.go`**
  Remove unused function `DetectCPPTestFramework` and its test `cpp_tests_test.go`, or integrate it if required.
  Verify `go test ./internal/detect/...` passes.

---

### Task 2: Fix Hook Configuration & Installed Manifest

**Files:**
- Modify: `.claude/settings.json`
- Modify: `.ultraloom/installed.toml`

- [ ] **Step 1: Fix Stop hook project path in `.claude/settings.json`**
  Change line 70 from `${CLAUDE_PROJECT_DIR}/.ultraloom/vendor/ultraloom` to `${CLAUDE_PROJECT_DIR}`.
  Verify with `go run ./cmd/guard status`.

- [ ] **Step 2: Reconcile `.ultraloom/installed.toml`**
  Either remove `"GEMINI.md"` from `files` list or create `GEMINI.md` pointing to `AGENTS.md` (analogous to `CLAUDE.md`).

---

### Task 3: Fix German Messages in Python (AGENTS.md Compliance)

**Files:**
- Modify: `src/ultraloom/checks.py`
- Modify: `src/ultraloom/flows/verify_until_green.py`
- Modify: `tests/test_checks.py`
- Modify: `tests/flows/test_verify_until_green.py`

- [ ] **Step 1: Update warning in `src/ultraloom/checks.py:346`**
  Translate: `"Warning: `{after}` did not run in this pass; this report may originate from an older run."`
  Update corresponding test assertions in `tests/test_checks.py`.

- [ ] **Step 2: Update blocker message in `src/ultraloom/checks.py:696`**
  Translate: `f"did not run because `{blocker}` was red"`
  Update corresponding test assertions in `tests/test_checks.py`.

- [ ] **Step 3: Update flow message in `src/ultraloom/flows/verify_until_green.py:213`**
  Translate: `f"Did not run because a predecessor was red: {', '.join(blocked)}"`
  Update corresponding test assertions in `tests/flows/test_verify_until_green.py`.

- [ ] **Step 4: Verify test suite**
  Run `uv run pytest` and verify 911 passing tests with 100% coverage.

---

### Task 4: Fix Misleading and Outdated Comments

**Files:**
- Modify: `pyproject.toml`
- Modify: `.ultraloom/config.toml`
- Modify: `cmd/guard/status.go`

- [ ] **Step 1: Update `pyproject.toml` and `.ultraloom/config.toml`**
  Replace references to deleted `hooks/gofmt-check.py` with `ulinit check gofmt`.

- [ ] **Step 2: Correct status claims in `cmd/guard/status.go`**
  Remove "Size Limit" from PreToolUse status line (lines 110) and clarify non-code file exit conditions.

---

### Task 5: Root Artifact Clean-Up & `.gitignore` Anchoring

**Files:**
- Modify: `.gitignore`
- Delete untracked root artifacts

- [ ] **Step 1: Anchor `.gitignore` patterns to root**
  Change `*cov*` and `cover*` to explicit root patterns:
  `/coverage`, `/coverage.out`, `/cover`, `/guard_cover`, `/cov_*.out`.
  Remove useless `$*`.
  Verify `git check-ignore internal/coverage/check.go` is empty.

- [ ] **Step 2: Remove orphaned filesystem caches**
  Remove orphaned `tests/policy/` directory (only contains old `__pycache__`).
  Remove orphaned `src/ultraloom/hooks/__pycache__/post_edit.cpython-313.pyc`.
  Remove stray local binaries (`ulguard_new.exe`, `init`, `.out` files).

---

### Task 6: Prune Merged Git Worktrees (User Approval Dependent)

**Actions:**
- Remove merged worktree `.worktrees/installer-kern` (`git worktree remove .worktrees/installer-kern`).
- Remove merged worktree `.worktrees/cpp-stack-verify` (`git worktree remove .worktrees/cpp-stack-verify`).
- Clean empty leftover folders `.worktrees/bench-ultraloom` and `.claude/worktrees/teilprojekt-1-kern-tasks-1-8-88653d`.
- Inspect/retire detached worktree `.claude/worktrees/project-history-planning-cf98dc`.
