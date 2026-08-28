# Agent-Plattformen & Lifecycle-Hook-Reihenfolge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement agent platform selection (`claude,gemini` as default) and sort Claude Code hook events strictly by their official lifecycle order (`SessionStart` -> `PreToolUse` -> `PostToolUse` -> `SubagentStart` -> `SubagentStop` -> `Stop`).

**Architecture:** Extend `internal/answers` with `Project.Agents`, add interview question and `--agents` flag in `internal/interview` and `cmd/init`, emit hooks in lifecycle order in `hookEntries`, and ensure `internal/settings` preserves/sorts lifecycle event keys.

**Tech Stack:** Go 1.24, TOML parsing, JSON merge.

**Spec:** [docs/.superpowers/specs/2026-08-28-agents-and-lifecycle-hooks-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-28-agents-and-lifecycle-hooks-design.md)

---

### Task 1: Add `Project.Agents` to `internal/answers` and `internal/interview`

**Files:**
- Modify: `internal/answers/answers.go`
- Modify: `internal/answers/answers_test.go`
- Modify: `internal/interview/interview.go`
- Modify: `internal/interview/interview_test.go`

**Interfaces:**
- `Project.Agents`: `[]string{"claude", "gemini"}` default
- `interview.Missing`: question for `agents` with `--agents` flag

- [ ] **Step 1: Write tests for `Project.Agents` in answers and interview**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Update `answers.go` and `interview.go`**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

---

### Task 2: Lifecycle Hook Order and Flag Handling in `cmd/init`

**Files:**
- Modify: `cmd/init/run.go`
- Modify: `cmd/init/run_test.go`
- Modify: `internal/render/templates/answers.toml.tmpl`
- Modify: `internal/render/templates/config.toml.tmpl`
- Modify: `internal/render/render_test.go`

**Interfaces:**
- `Options.Agents`: `--agents` CLI flag
- `hookEntries`: ordered by `SessionStart` -> `PreToolUse` -> `PostToolUse` -> `SubagentStart` -> `SubagentStop` -> `Stop`
- `mergeSettings`: called if `claude` in `Agents`

- [ ] **Step 1: Write unit tests for lifecycle hook ordering and `--agents` flag**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement lifecycle ordering and agent flag in `run.go` and templates**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

---

### Task 3: Full Gate & End-to-End Verification

**Files:**
- Test: `uv run ultraloom check all`
- Test: Run `ulinit.exe` against `.worktrees/test-installer` in `space` repo and verify output files and `.claude/settings.json`.

- [ ] **Step 1: Run full gate `uv run ultraloom check all`**
- [ ] **Step 2: Run `ulinit.exe` against space worktree**
- [ ] **Step 3: Verify `.claude/settings.json` has lifecycle order and `answers.toml` has `agents = ["claude", "gemini"]`**
- [ ] **Step 4: Commit and finalize**
