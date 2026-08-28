# Nativer Policy-Guard (P5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native Go policy guard binary `cmd/guard` that evaluates `.ultraloom/policy.toml` against hook JSON payloads from `stdin` in < 15ms.

**Architecture:** Create `cmd/guard/main.go` and `cmd/guard/guard.go` with pure evaluation logic. Handle path globs and command regexes. Return exit 0 (allow), exit 2 (block), exit 1 (error).

**Tech Stack:** Go 1.24, `github.com/BurntSushi/toml`, `bmatcuk/doublestar/v4` or standard `path/filepath` / glob matching, `regexp`.

**Spec:** [docs/.superpowers/specs/2026-08-28-guard-nativ-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-28-guard-nativ-design.md)

---

### Task 1: Implement `cmd/guard` Logic & Unit Tests

**Files:**
- Create: `cmd/guard/main.go`
- Create: `cmd/guard/guard.go`
- Create: `cmd/guard/guard_test.go`

- [ ] **Step 1: Write unit tests in `cmd/guard/guard_test.go` for policy parsing, path matching, command matching, and exit codes**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement policy evaluation in `cmd/guard/guard.go` and CLI runner in `cmd/guard/main.go`**
- [ ] **Step 4: Run `go test -cover ./cmd/guard` and verify 100% statement coverage**
- [ ] **Step 5: Commit**

---

### Task 2: Integrate `cmd/guard` into Hook Generation & Verification

**Files:**
- Modify: `cmd/init/run.go`
- Modify: `cmd/init/run_test.go`

- [ ] **Step 1: Update PreToolUse hook command in `cmd/init/run.go` if applicable**
- [ ] **Step 2: Run `go test ./...` and `uv run ultraloom check all`**
- [ ] **Step 3: Commit**

---

### Task 3: Full Gate & End-to-End Verification

**Files:**
- Test: `uv run ultraloom check all`
- Test: Build `ulguard.exe` and test with sample payloads

- [ ] **Step 1: Test `ulguard.exe` with `git push` payload (verify exit 2)**
- [ ] **Step 2: Test `ulguard.exe` with safe payload (verify exit 0)**
- [ ] **Step 3: Run full gate `uv run ultraloom check all`**
- [ ] **Step 4: Commit and finalize**
