# Repository Hook, Language & Tooling Inventory (`#GIT`)

**Date:** 2026-08-29  
**Status:** Approved Reference  
**Scope:** Complete inventory of all git repositories located under `C:\Users\micro\Documents\#GIT`, their language stacks, active git hook mechanisms, agent lifecycle hooks, linters, formatters, and test runners.

---

## 1. Executive Summary

A comprehensive scan across all 34 directories in `c:\Users\micro\Documents\#GIT` revealed 4 distinct categories of repositories:

1. **UltraLoom & Core Agent Infrastructure (`ultraloom`, `ultra-brain`):**
   * Multi-language Go/Python setup or pure Python with high-rigor quality gates (100% test coverage floor, strict typing, linting).
   * Dual hook architecture: Git hooks (`pre-commit`, `pre-push`) + LLM Agent hooks (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`).
   * UltraLoom native policy engine (`ulguard`), write barriers (`wiki_guard.py`), and initialization shims (`ulinit`).

2. **Full-Stack & Domain Applications (`iam_backend`, `iam_frontend`, `space`, `odysseus`, `open-design`):**
   * Rich, domain-specific quality checks: Django system checks & migrations, Docker service health checks (`ensure_postgres.py`), GDScript static analysis (`gdlint`), Godot headless test suites, Biome/ESLint, Vitest coverage.
   * Dedicated commit-message language enforcement (`commit_language.py` in `space`).

3. **Specialized Libraries, Tools & Backends (`nano-coverage-godot`, `RepoMapper`, `deepSWE`, `iam_workers`, `label-studio-ml-backend`, `hashprobe`):**
   * C++ GDExtension (`clang-format`, SCons), Celery workers (Makefile), .NET C# (`P.csproj`), Python Tree-sitter tools.

4. **Knowledge Bases, Notes & Static Assets (`#Obsidian`, `brain-knowledge`, `iam_wiki`, `iam_docs`, `iam_design`):**
   * Markdown vaults, design assets, and unstructured/semi-structured notes.

---

## 2. Detailed Per-Project Matrix

| Repository | Primary Languages | Git Hook Integration | Agent Lifecycle Hooks | Active Linters, Formatters & Tooling |
| :--- | :--- | :--- | :--- | :--- |
| **`ultraloom`** | Go, Python | `core.hooksPath = .githooks`<br>• `pre-commit` (`uv run ultraloom check all`) | • `SessionStart`: `ultraloom hook session-start`<br>• `PreToolUse`: `ulguard` (Go binary) + `wiki_guard.py`<br>• `PostToolUse`: `ruff check`, `dmypy run`<br>• `Stop` / `SubagentStop`: `ultraloom hook stop` | • **Go:** `gofmt`, `go vet`, `go test`<br>• **Python:** `uv`, `ruff`, `dmypy` (daemon), `pytest`, `coverage`<br>• **Custom Helpers:** `hooks/coverage-check.py` (98% floor), `hooks/gofmt-check.py`<br>• **Policy:** `[policy.paths.rules]`, `[policy.commands.rules]` |
| **`ultra-brain`** | Python | `core.hooksPath = hooks/git`<br>• `pre-commit` (staged diffs)<br>• `pre-push` (`ultraloom check all`) | • `PreToolUse`: `wiki_guard.py` (Write barrier against unauthorized overwrites) | • `uv run --no-sync`<br>• `ruff check src tests`<br>• `mypy src tests`<br>• `pytest` (`-m 'not contract'`) under `coverage run`<br>• `coverage report` (100% threshold) |
| **`space`** | GDScript (Godot 4), Python, Godot Shaders | `core.hooksPath = .githooks`<br>• `pre-commit` (`quality.py`, `godot_quality.py`)<br>• `commit-msg` (`commit_language.py`) | • `SessionStart`: `session_start.py`<br>• `PostToolUse`: `post_edit.py`<br>• `Stop`: `generate_index.py`, `lint.py` | • **GDScript:** `gdlint` (`.gdlintrc`), Godot Headless Engine testrunner & coverage, boundary checks<br>• **Python:** `ruff`, `mypy`, `quality.py`<br>• **Gate:** `commit_language.py` (blocks German commit messages) |
| **`iam_backend`** | Python (Django, PostgreSQL) | `core.hooksPath = .githooks`<br>• `.pre-commit-config.yaml`<br>• `.git/hooks/pre-commit`<br>• `.git/hooks/pre-push` | *(None configured)* | • `uv run`<br>• `ruff`, `djlint` (Django templates), `pyright`, `mypy` (strict), `bandit`, `pip-audit`<br>• `ensure_postgres.py` (Docker Postgres container auto-start & readiness probe)<br>• `manage.py check`, `makemigrations --check --dry-run`, `compilemessages`<br>• `pytest --cov --cov-fail-under=100` |
| **`iam_frontend`** | TypeScript, React, HTML/CSS | Husky (`.husky/pre-commit`) | *(None configured)* | • `docker compose exec frontend`<br>• `vitest run --coverage`<br>• `eslint .`<br>• `tsc --noEmit` |
| **`open-design`** | TypeScript, Next.js, React | Monorepo (pnpm) | *(None configured)* | • `biome` (linter/formatter), `eslint`, `vitest`, `playwright`, `tailwind` |
| **`odysseus`** | Python, TypeScript/React | Multi-Service | *(None configured)* | • `pytest`, `eslint`, Docker Compose |
| **`iam_workers`** | Python (Celery) | Makefile | *(None configured)* | • `make`, `celery`, `pytest`, `ruff` |
| **`label-studio-ml-backend`** | Python | Makefile | *(None configured)* | • `make`, `pytest`, `flake8`, `codecov` |
| **`nano-coverage-godot`** | C++, Godot Cpp | SConstruct | *(None configured)* | • `clang-format` (`.clang-format`), SCons, C++20 |
| **`deepSWE`** | Python | UV Setup | *(None configured)* | • `uv`, Benchmarking harnesses |
| **`RepoMapper`** | Python | UV Setup | *(None configured)* | • `tree-sitter`, `pytest`, `uv` |
| **`hashprobe`** | C# (.NET) | MSBuild / Visual Studio | *(None configured)* | • `dotnet`, `P.csproj` |
| **`cpr-compress-preserve-resume`** | Python, Shell | Standalone scripts | *(None configured)* | • CLI utilities |
| **`ecoflow`**, **`OF`**, **`PI`**, **`AgentProof`**, **`LM-Studio-Bench`**, **`factorio`**, **`HA`**, **`spore-klone`**, **`django_yolo`** | Python / Lua / YAML / GDScript | *(None)* | *(None)* | Standard package setups |
| **`#Obsidian`**, **`brain-knowledge`**, **`iam_wiki`**, **`iam_docs`**, **`iam_design`** | Markdown / Docs | *(None)* | *(None)* | Obsidian Vaults, Documentation |

---

## 3. Language & Tooling Ecosystem Analysis

### 3.1 Python Ecosystem
* **Package Management:** Universal adoption of `uv` (`uv run`, `uvx`, `uv.lock`).
* **Linting & Formatting:** `ruff` is dominant. `djlint` used for Django HTML templates.
* **Type Checking:** `mypy` (often with `dmypy` daemon for <1s checks) and `pyright` (in `iam_backend`).
* **Testing & Coverage:** `pytest` with mandatory 100% test coverage gate (`--cov-fail-under=100`).
* **Security:** `bandit` (static AST security audit) and `pip-audit` (vulnerable dependencies).

### 3.2 Go Ecosystem
* **Format & Lint:** `gofmt` (currently wrapped in Python by UltraLoom) and `go vet`.
* **Testing & Coverage:** `go test ./...` and `go tool cover -func` (enforced with 98% statement coverage floor).
* **Binaries:** `ulguard` (high-speed PreToolUse hook) and `ulinit` (repo scaffolding & installer).

### 3.3 TypeScript / JavaScript Ecosystem
* **Format & Lint:** `biome` (high performance in modern repos) and `eslint` + `prettier`.
* **Type Checking:** `tsc --noEmit`.
* **Testing:** `vitest` with native coverage and `playwright` for end-to-end testing.
* **Execution Environment:** Bare metal (Node/pnpm) and containerized (`docker compose exec frontend`).

### 3.4 GDScript / Godot Ecosystem
* **Linting:** `gdlint` via `gdtoolkit` with `.gdlintrc`.
* **Test & Coverage:** Custom headless Godot test runners (`godot_quality.py`).
* **Boundary Checks:** Verification of scene/script architectural boundaries.

---

## 4. Gaps, Inefficiencies & Opportunities for UltraLoom

1. **Python Shims for Go Verification in UltraLoom:**
   * UltraLoom uses Python scripts (`hooks/gofmt-check.py`, `hooks/coverage-check.py`) to verify its own Go code.
   * Under Windows, spawning Python and sub-shells adds significant latency and environment resolution issues (e.g. WSL vs. Windows path conflicts).

2. **Commit Message Quality Gate is Isolated in `space`:**
   * `space` has a proven `commit-msg` gate (`commit_language.py`) that stops non-English commits. This capability should be a first-class feature in UltraLoom for all repositories.

3. **External Pre-Commit Dependencies:**
   * Repos like `iam_backend` still use the Python `pre-commit` framework with `.pre-commit-config.yaml`, creating multiple tool chains and slower execution than direct shims.

4. **Service & Container Readiness Verification:**
   * Full-stack projects require services (like PostgreSQL in `iam_backend`) to run tests. UltraLoom currently assumes all local dependencies are already running.
