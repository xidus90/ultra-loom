# Dokumentvorlagen (P3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate standard instruction templates (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) during `ultraloom init` based on selected agents and project languages.

**Architecture:** Add embedded templates in `internal/render/templates/` for `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`. Update `internal/render/render.go` to render these files based on `answers.Project.Agents`, and ensure `internal/write` / `cmd/init` commits them safely without overwriting existing files.

**Tech Stack:** Go 1.24, `html/template` / `text/template`.

**Spec:** [docs/.superpowers/specs/2026-08-28-dokumentvorlagen-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-28-dokumentvorlagen-design.md)

---

### Task 1: Create Document Templates in `internal/render`

**Files:**
- Create: `internal/render/templates/AGENTS.md.tmpl`
- Create: `internal/render/templates/CLAUDE.md.tmpl`
- Create: `internal/render/templates/GEMINI.md.tmpl`
- Modify: `internal/render/render.go`
- Modify: `internal/render/render_test.go`

**Interfaces:**
- Produces: `Render(answers Answers, coverageLane bool) (map[string]string, error)` including `AGENTS.md`, and conditionally `CLAUDE.md` / `GEMINI.md`.

- [ ] **Step 1: Write test for rendering `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Add template files and update `render.go`**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

---

### Task 2: Update `cmd/init` & Integration Tests

**Files:**
- Modify: `cmd/init/run.go`
- Modify: `cmd/init/run_test.go`

- [ ] **Step 1: Write integration tests for generated markdown documents**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Update `cmd/init` if needed and verify file creation & skip behavior**
- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Commit**

---

### Task 3: Full Gate & End-to-End Verification

**Files:**
- Test: `uv run ultraloom check all`
- Test: Build `ulinit.exe` and test against `.worktrees/test-installer` in `space` repo.

- [ ] **Step 1: Run full gate `uv run ultraloom check all`**
- [ ] **Step 2: Run `ulinit.exe` against space worktree**
- [ ] **Step 3: Verify created files**
- [ ] **Step 4: Commit and finalize**
