# Tooling-Check, PATH-Auflösung & Tool-Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement tooling check against `$PATH`, interactive path prompting / auto-installation for missing tools, and full suite pre-commit hook installation.

**Architecture:** Create `internal/tooling/check.go` for finding tools on `$PATH` and triggering installers. Update `internal/interview` and `cmd/init/run.go` to prompt/install missing tools and configure `.githooks/pre-commit`.

**Tech Stack:** Go 1.24, `os/exec`, `path/filepath`.

**Spec:** [docs/.superpowers/specs/2026-08-28-tooling-check-and-install-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-28-tooling-check-and-install-design.md)

---

### Task 1: Implement `internal/tooling` Package

**Files:**
- Create: `internal/tooling/tooling.go`
- Create: `internal/tooling/tooling_test.go`

- [x] **Step 1: Write unit tests in `internal/tooling/tooling_test.go`**
- [x] **Step 2: Implement `FindTool`, `CheckStacks`, `InstallTool` in `internal/tooling/tooling.go`**
- [x] **Step 3: Run `go test -cover ./internal/tooling` and verify 100% statement coverage**
- [x] **Step 4: Commit**

---

### Task 2: Integrate Tooling Check into Interview & CLI Flags

**Files:**
- Modify: `internal/interview/interview.go`
- Modify: `internal/interview/interview_test.go`
- Modify: `cmd/init/run.go`
- Modify: `cmd/init/run_test.go`

- [ ] **Step 1: Add interactive questions for missing tools in `internal/interview`**
- [ ] **Step 2: Add `--tool-path` / `--install-tools` flags in `cmd/init`**
- [ ] **Step 3: Run `go test ./...` and verify coverage**
- [ ] **Step 4: Commit**

---

### Task 3: Pre-commit Hook with Full Suite Installation

**Files:**
- Modify: `internal/render/render.go`
- Modify: `internal/render/render_test.go`
- Modify: `cmd/init/run.go`
- Modify: `cmd/init/run_test.go`

- [ ] **Step 1: Update `render.go` to ensure `precommit = ["lint", "types", "test", "coverage"]` (full suite)**
- [ ] **Step 2: Update `cmd/init/run.go` to write `.githooks/pre-commit` and run `git config core.hooksPath .githooks`**
- [ ] **Step 3: Test on `space` worktree**
- [ ] **Step 4: Run full gate `uv run ultraloom check all`**
- [ ] **Step 5: Commit**
