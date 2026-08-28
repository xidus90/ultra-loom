# Agent-Ausstattung (P4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide projects with standard agent skills (`verify-until-green`, `session-handover`) in `.claude/skills/` and/or `.agents/skills/` based on `[project].agents`.

**Architecture:** Embed skills in `internal/render/templates/skills/` and render them conditionally into `.claude/skills/...` and `.agents/skills/...` in `internal/render/render.go`.

**Tech Stack:** Go 1.24, `embed.FS`, `text/template`.

**Spec:** [docs/.superpowers/specs/2026-08-28-agent-ausstattung-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-28-agent-ausstattung-design.md)

---

### Task 1: Add Skill Templates and Update `internal/render`

**Files:**
- Create: `internal/render/templates/skills/verify-until-green.SKILL.md.tmpl`
- Create: `internal/render/templates/skills/session-handover.SKILL.md.tmpl`
- Modify: `internal/render/render.go`
- Modify: `internal/render/render_test.go`

- [ ] **Step 1: Create template files in `internal/render/templates/skills/`**
- [ ] **Step 2: Update `internal/render/render.go` to render skills for claude and gemini**
- [ ] **Step 3: Update `internal/render/render_test.go` with unit tests for skill paths**
- [ ] **Step 4: Run `go test ./internal/render` to verify**
- [ ] **Step 5: Commit changes**

---

### Task 2: Update Integration Tests in `cmd/init`

**Files:**
- Modify: `cmd/init/run_test.go`

- [ ] **Step 1: Add integration tests in `cmd/init/run_test.go` for skill creation & protection**
- [ ] **Step 2: Run `go test ./...` and verify statement coverage >= 98.0%**
- [ ] **Step 3: Commit changes**

---

### Task 3: Full Gate & End-to-End Verification

**Files:**
- Test: `uv run ultraloom check all`
- Test: Build `ulinit.exe` and test against `space` worktree

- [ ] **Step 1: Run `ulinit.exe` against space worktree and inspect created skills**
- [ ] **Step 2: Run full gate `uv run ultraloom check all`**
- [ ] **Step 3: Commit and finalize**
