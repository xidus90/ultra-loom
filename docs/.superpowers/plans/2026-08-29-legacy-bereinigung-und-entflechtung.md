# Legacy Cleanup & Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove legacy Python wrapper modules (`post_edit.py`, `policy/`, `toolchain.py`), decouple `cli.py` / `checks.py`, update `.githooks/pre-commit`, and document all active commands in `README.md` and `README.de.md`.

**Architecture:** Purge obsolete Python hooks and policy code that have been superseded by native Go components (`cmd/init`, `cmd/guard`) and direct Tier-1 shims. Keep the core Python Agent Flow engine (`verify-until-green`, graph, journal, worktree, model port) and commit language verifier intact. Update bilingual documentation with the definitive command catalog.

**Tech Stack:** Python 3.13, Go 1.24, pytest, Git Hooks.

**Spec:** [docs/.superpowers/specs/2026-08-29-legacy-bereinigung-und-entflechtung-design.md](file:///c:/Users/micro/Documents/%23GIT/ultraloom/docs/.superpowers/specs/2026-08-29-legacy-bereinigung-und-entflechtung-design.md)

## Global Constraints
- Commit messages and code comments must be in English.
- Commits must carry the user as author and committer without agent attribution tags.
- Documentation must be bilingual (`README.md` in English, `README.de.md` in German).
- Minimum statement test coverage: Python 100%, Go 98.0%.

---

### Task 1: Delete Obsolete Python Modules and Tests

**Files:**
- Delete: `src/ultraloom/hooks/post_edit.py`
- Delete: `tests/hooks/test_post_edit.py`
- Delete: `src/ultraloom/policy/` (all 5 files: `__init__.py`, `cli.py`, `config.py`, `hook.py`, `rules.py`)
- Delete: `tests/policy/` (all 4 files: `test_cli.py`, `test_config.py`, `test_hook.py`, `test_rules.py`)
- Delete: `src/ultraloom/toolchain.py`
- Delete: `tests/test_toolchain.py`

**Interfaces:**
- Consumes: None
- Produces: Cleaned `src/ultraloom/` tree with legacy wrappers removed.

- [x] **Step 1: Remove legacy files**
- [x] **Step 2: Verify removals via git status**
- [x] **Step 3: Commit deletion**

---

### Task 2: Streamline `cli.py`, `hooks/cli.py`, and `checks.py`

**Files:**
- Modify: `src/ultraloom/cli.py`
- Modify: `src/ultraloom/hooks/cli.py`
- Modify: `src/ultraloom/checks.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/hooks/test_cli.py`

**Interfaces:**
- Consumes: `src/ultraloom/cli.py`
- Produces: Cleaned CLI without `policy` or `hook post-edit` subcommands; simplified `checks.py` without `toolchain` import.

- [x] **Step 1: Remove `policy` and `hook post-edit` subcommands from `src/ultraloom/cli.py`**
- [x] **Step 2: Update `src/ultraloom/hooks/cli.py` to remove `post-edit` dispatch**
- [x] **Step 3: Remove `toolchain` references from `src/ultraloom/checks.py`**
- [x] **Step 4: Update CLI and hooks test suites in `tests/test_cli.py` and `tests/hooks/test_cli.py`**
- [x] **Step 5: Run `uv run pytest` to verify 100% test pass and 100% Python coverage**
- [x] **Step 6: Commit**

---

### Task 3: Update `.githooks/pre-commit` Generation & Full Quality Gate

**Files:**
- Modify: `cmd/init/run.go`
- Modify: `cmd/init/run_test.go`

**Interfaces:**
- Consumes: `cmd/init/run.go`
- Produces: `preCommitHook` generating `uv run ultraloom check all`.

- [x] **Step 1: Update `preCommitHook` in `cmd/init/run.go` to use `uv run ultraloom check all`**
- [x] **Step 2: Update assertions in `cmd/init/run_test.go`**
- [x] **Step 3: Run `go test ./...` and verify $\ge 98.0\%$ Go statement coverage**
- [x] **Step 4: Run full quality gate `uv run ultraloom check all`**
- [x] **Step 5: Commit**

---

### Task 4: Bilingual Documentation of Command Inventory in README

**Files:**
- Modify: `README.md`
- Modify: `README.de.md`

**Interfaces:**
- Consumes: Complete command inventory (Go installer & runtime commands, UltraLoom flow & commit commands).
- Produces: Up-to-date bilingual documentation outlining installer commands (`ulinit`, `ulguard`) and CLI commands (`ultraloom run`, `ultraloom check`, `ultraloom commit-msg`).

- [x] **Step 1: Update `README.md` with the full categorized command reference**
- [x] **Step 2: Update `README.de.md` with the German translation of the command reference**
- [x] **Step 3: Verify cross-links between `README.md` and `README.de.md`**
- [x] **Step 4: Run `uv run ultraloom check all`**
- [x] **Step 5: Commit**
