# Performance Benchmarks

[Deutsche Version](benchmarks.de.md)

### Current Benchmark Summary (Quick Reference)

The tables below summarize the latest performance measurements across all 5 benchmarked repositories, toolchains, and lifecycle events, comparing unoptimized baseline execution against the UltraLoom native architecture.

### Multi-Repository End-to-End Suite Overview

| Repository & Stack | Event / Target File | Invoked Tools | Cold Latency | Warm Latency | Evaluation & Status |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **`space`**<br>*(Godot / GDScript / C++ / Wiki)* | `PreToolUse` (Safe Edit)<br>`PreToolUse` (Protected `.env`)<br>`PostToolUse` (`plugin.gd`)<br>`PostToolUse` (`SPEC.md` Doc)<br>`PostToolUse` (`wiki/.../index.md`)<br>`Stop` (`brain wiki-gate`) | `ulguard`<br>`ulguard` (Refusal)<br>`gdlint`<br>*[BYPASSED]*<br>`brain lint`<br>`brain wiki-gate` | 29.2 ms<br>27.4 ms<br>276.0 ms<br>36.9 ms<br>1,096.5 ms<br>1,190.9 ms | **27.2 ms**<br>**27.4 ms**<br>**252.5 ms**<br>**35.8 ms**<br>**986.2 ms**<br>**1,207.1 ms** | 🛡️ Blocks `.env` in 27 ms<br>⚡ 9.1x faster than legacy hook<br>🚀 64.4x faster than legacy hook<br>🔍 Validates OKF bundle links |
| **`iam_backend`**<br>*(Django / Python / Docker)* | `PreToolUse` (Safe Edit)<br>`PreToolUse` (Protected `.env`)<br>`PostToolUse` (`manage.py`)<br>`PostToolUse` (`README.md` Doc) | `ulguard`<br>`ulguard` (Refusal)<br>`ruff` + `dmypy`<br>*[BYPASSED]* | 30.8 ms<br>27.9 ms<br>245.5 ms<br>48.6 ms | **27.5 ms**<br>**27.9 ms**<br>**259.2 ms**<br>**52.1 ms** | 🛡️ Blocks `.env` in 28 ms<br>⚡ Concurrent Ruff + dmypy<br>🚀 4.0x faster than legacy hook |
| **`iam_workers`**<br>*(Python 3.13 / UV / Pyright)* | `PreToolUse` (Safe Edit)<br>`PreToolUse` (Protected `.env`)<br>`PostToolUse` (`worker.py`)<br>`PostToolUse` (`README.md` Doc) | `ulguard`<br>`ulguard` (Refusal)<br>`ruff` + `pyright`<br>*[BYPASSED]* | 30.1 ms<br>25.1 ms<br>1,713.6 ms<br>30.5 ms | **25.7 ms**<br>**25.1 ms**<br>**1,650.0 ms**<br>**32.2 ms** | 🛡️ Blocks `.env` in 25 ms<br>⚡ Concurrent Ruff + Pyright strict<br>🚀 5.3x faster than legacy hook |
| **`iam_frontend`**<br>*(React 19 / TS / Vite / ESLint 9)* | `PreToolUse` (Safe Edit)<br>`PreToolUse` (Protected `.env`)<br>`PostToolUse` (`App.tsx`)<br>`PostToolUse` (`README.md` Doc) | `ulguard`<br>`ulguard` (Refusal)<br>`eslint --cache` + `tsc`<br>*[BYPASSED]* | 31.3 ms<br>28.9 ms<br>2,123.7 ms<br>31.4 ms | **30.9 ms**<br>**28.9 ms**<br>**1,787.9 ms**<br>**33.4 ms** | 🛡️ Blocks `.env` in 29 ms<br>⚡ Concurrent ESLint 9 + tsc<br>🚀 6.3x faster than legacy hook |
| **`ultra-brain`**<br>*(Python / Go Core)* | `PreToolUse` (Safe Edit)<br>`PreToolUse` (Protected `.env`)<br>`PostToolUse` (`cli.py`)<br>`PostToolUse` (`README.md` Doc)<br>`PostToolUse` (`docs/wiki/index.md`)<br>`Stop` (`brain wiki-gate`) | `ulguard`<br>`ulguard` (Refusal)<br>`ruff` + `mypy`<br>*[BYPASSED]*<br>`brain lint` (Go Native)<br>`brain wiki-gate` (Go Native) | 29.5 ms<br>26.1 ms<br>533.7 ms<br>46.3 ms<br>143.9 ms<br>229.5 ms | **27.0 ms**<br>**26.1 ms**<br>**243.9 ms**<br>**49.2 ms**<br>**25.5 ms**<br>**98.5 ms** | 🛡️ Blocks `.env` in 26 ms<br>⚡ Parallel goroutines<br>🚀 35.1x faster than Python CLI<br>🛡️ Sub-100ms full bundle gate |
| **`ultraloom`**<br>*(Go Core)* | `PreToolUse` (Safe Edit)<br>`PreToolUse` (Protected `.env`)<br>`PostToolUse` (`main.go`)<br>`PostToolUse` (`README.md` Doc) | `ulguard`<br>`ulguard` (Refusal)<br>`go vet ./...`<br>*[BYPASSED]* | 29.9 ms<br>28.4 ms<br>505.1 ms<br>41.1 ms | **26.5 ms**<br>**28.4 ms**<br>**293.0 ms**<br>**35.9 ms** | 🛡️ Blocks `.env` in 28 ms<br>⚡ Fast static analysis<br>🚀 Instant bypass |

### Toolchain Speedup Comparison (Optimized vs. Baseline)

| Project | Target / File Type | Invoked Toolchain | Baseline (No Loom / Legacy) | Optimized (UltraLoom) | Speedup / Savings (Warm) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **`space`** | Markdown Doc (`SPEC.md`) | `ulguard post-edit` (Instant Exit) | Cold: 2,447.2 ms<br>Warm: 2,305.7 ms | Cold: 36.9 ms<br>Warm: **35.8 ms** | 🚀 **64.4x faster**<br>(~2.27 s saved / turn) |
| **`space`** | GDScript Code (`plugin.gd`) | `ulguard post-edit` (`gdlint <file>`) | Cold: 2,344.2 ms<br>Warm: 2,300.3 ms | Cold: 276.0 ms<br>Warm: **252.5 ms** | ⚡ **9.1x faster**<br>(~2.05 s saved / turn) |
| **`iam_backend`** | Markdown Doc (`README.md`) | `ulguard` + `ulguard post-edit` | Cold: 224.0 ms<br>Warm: 206.7 ms | Cold: 48.6 ms<br>Warm: **52.1 ms** | 🚀 **4.0x faster**<br>(~154 ms saved / turn) |
| **`iam_backend`** | Python Code (`manage.py`) | `ulguard` + `ulguard post-edit` (`ruff` + `dmypy` parallel) | Cold: 311.4 ms<br>Warm: 311.3 ms *(Ruff only)* | Cold: 245.5 ms<br>Warm: **259.2 ms** | ⚡ **1.2x faster**<br>(+ full static type check) |
| **`iam_workers`** | Python Code (`worker.py`) | `ulguard` + `ulguard post-edit` (`ruff` + `pyright` parallel) | Cold: 2,850.0 ms<br>Warm: 2,720.0 ms *(Sequential)* | Cold: 1,713.6 ms<br>Warm: **1,650.0 ms** | ⚡ **1.7x faster**<br>(+ full Pyright strict check) |
| **`iam_workers`** | Markdown Doc (`README.md`) | `ulguard` + `ulguard post-edit` | Cold: 210.0 ms<br>Warm: 188.0 ms | Cold: 30.5 ms<br>Warm: **32.2 ms** | 🚀 **5.8x faster**<br>(Instant bypass) |
| **`iam_frontend`** | TypeScript Code (`App.tsx`) | `ulguard post-edit` (`eslint --cache` + `tsc` parallel) | Cold: 12,450.0 ms<br>Warm: 11,200.0 ms *(Sequential)* | Cold: 2,123.7 ms<br>Warm: **1,787.9 ms** | 🚀 **6.3x faster**<br>(~9.41 s saved / turn) |
| **`iam_frontend`** | Markdown Doc (`README.md`) | `ulguard` + `ulguard post-edit` | Cold: 215.0 ms<br>Warm: 195.0 ms | Cold: 31.4 ms<br>Warm: **33.4 ms** | 🚀 **5.8x faster**<br>(Instant bypass) |
| **`ultra-brain`** | Wiki Doc Edit (`docs/wiki/index.md`) | `ulguard post-edit` (`brain lint <file>` Go) | Cold: 924.7 ms<br>Warm: 896.1 ms *(Python CLI)* | Cold: 143.9 ms<br>Warm: **25.5 ms** | 🚀 **35.1x faster**<br>(~870 ms saved / turn) |
| **`ultra-brain`** | Python Code (`src/brain/cli.py`) | `ulguard post-edit` (`ruff` + `mypy` parallel) | Cold: 533.7 ms<br>Warm: 243.9 ms | Cold: 533.7 ms<br>Warm: **243.9 ms** | ⚡ **Native parallel execution** |
| **`ultraloom`** | Go Code (`cmd/guard/main.go`) | `ulguard post-edit` (`go vet ./...`) | Cold: 505.1 ms<br>Warm: 293.0 ms | Cold: 505.1 ms<br>Warm: **293.0 ms** | ⚡ **Fast static analysis** |
| **`ultra-brain` / `space`** | Session End Wiki Gate | Stop hook (`brain wiki-gate` Go) | Cold: 961.3 ms<br>Warm: 1,033.8 ms *(Python)* | Cold: 229.5 ms<br>Warm: **98.5 ms** | 🛡️ **10.5x faster**<br>(Sub-100ms full bundle gate) |

---

## Future Optimization Roadmap

* **Option B (UltraBrain Deep Go Migration):**
  * Port the **MCP Server** (`brain.mcp`) and **Hybrid Search Engine** (`brain search`) into native Go.
  * Eliminates the Python daemon process and reduces MCP memory footprint from ~120 MB down to **< 15 MB**.
  * Enables instant streaming tool responses (< 2 ms) for AI agents querying the wiki catalog.

---

## Chronological Benchmark Log

### 2026-08-31 19:35:00 CEST — UltraBrain Core Migration: Python vs. Go Native

* **Repository:** `ultra-brain` (Branch: `feature/go-brain-core` merged into `feature/ultra-brain-project-folder`)
* **Objective:** Benchmark the native Go implementation (`brain.exe`) against the original Python 3.13 / UV CLI across all primary wiki lifecycle events.
* **Findings:**
  * `brain lint <file>` dropped from **896.1 ms** down to **25.5 ms** (**35.1x faster**).
  * `brain wiki-gate` dropped from **1,033.8 ms** down to **98.5 ms** (**10.5x faster**).
  * `brain catalog` dropped from **937.1 ms** down to **31.2 ms** (**30.1x faster**).

| Command | Python 3.13 Baseline | Go Native Binary | Speedup |
| :--- | :---: | :---: | :---: |
| `brain lint docs/wiki/index.md` | Cold: 924.7 ms<br>Warm: 896.1 ms | Cold: 143.9 ms<br>Warm: **25.5 ms** | 🚀 **35.1x faster** |
| `brain wiki-gate` (Full Bundle) | Cold: 961.3 ms<br>Warm: 1,033.8 ms | Cold: 229.5 ms<br>Warm: **98.5 ms** | ⚡ **10.5x faster** |
| `brain catalog` (Index Dump) | Cold: 1,154.1 ms<br>Warm: 937.1 ms | Cold: 32.8 ms<br>Warm: **31.2 ms** | 🚀 **30.1x faster** |

* **Repositories:** `ultra-brain`, `ultraloom`
* **Objective:** Validate the two-tier verification architecture: Fast per-file linting on edit (`PostToolUse`) versus full bundle drift & link validation at session end (`Stop`).
* **Findings:** Post-edit single-file check runs in **~29.8 ms**. Non-wiki markdown edits bypass processing with **33.0 ms** warm latency. Full bundle validation runs at session end in **~967.1 ms**.

| Verification Tier | Invocation Event | Cold Latency | Warm Latency | Scope |
| :--- | :--- | :---: | :---: | :--- |
| **Tier 1: Post-Edit (Default / Wiki OFF)** | `PostToolUse` (`README.md`) | 150.5 ms | **33.0 ms** | Instant exit without child processes |
| **Tier 1: Post-Edit (Wiki ON)** | `PostToolUse` (`wiki/index.md`) | 31.7 ms | **29.8 ms** | Fast single-file `brain lint <file>` |
| **Tier 2: Stop-Hook (Full Wiki)** | `Stop` hook (`brain wiki-gate`) | 1,052.5 ms | **967.1 ms** | Full drift check + bundle validation |

---

### 2026-08-31 16:36:30 CEST — Stop-Hook Wiki Gate: Legacy vs. Domain-Native `brain wiki-gate`

* **Repositories:** `iam_backend` (neighbour wiki `iam_wiki`), `space` (local wiki `wiki/`)
* **Objective:** Compare legacy Git-only `wiki_gate.py` against `ultra-brain` native `brain wiki-gate` (Git-drift detection + full OKF bundle structural linting).
* **Findings:** `brain wiki-gate` completes comprehensive concept, frontmatter, and link validation across the entire wiki bundle in ~1.0 s at session completion.

| Mode / Project | Legacy `wiki_gate.py` (Git commit only) | `brain wiki-gate` (Drift + Full OKF Lint) |
| :--- | :---: | :---: |
| **`iam_backend` (`iam_wiki`)** | Cold: 152.6 ms<br>Warm: 146.7 ms | Cold: 1,088.5 ms<br>Warm: **1,128.4 ms** |
| **`space` (`wiki/`)** | *N/A (manual scripts)* | Cold: 1,050.2 ms<br>Warm: **1,115.7 ms** |

---

### 2026-08-31 14:58:26 CEST — Cleaned `install_loom` Branches (Full Edit-Turn Lifecycle)

* **Repositories:** `space` (branch `install_loom`), `iam_backend` (branch `install_loom`)
* **Objective:** Measure the complete Claude Code turn cycle (`PreToolUse` security guard + `PostToolUse` linters) after removing obsolete legacy hooks (`guard_paths.py`, `format_on_edit.py`, `post_edit.py`).
* **Findings:** Complete elimination of redundant Python processes during edits.

| Project & Scenario | Legacy Setup (`Pre` + `Post`) | Clean UltraLoom (`ulguard` + `ulguard post-edit`) | Speedup (Warm) |
| :--- | :---: | :---: | :---: |
| **`space` — `SPEC.md`** | Cold: 2,447.2 ms<br>Warm: 2,305.7 ms | Cold: 143.7 ms<br>Warm: **27.6 ms** | 🚀 **83.4x faster** (~2.28 s saved / turn) |
| **`space` — `plugin.gd`** | Cold: 2,344.2 ms<br>Warm: 2,300.3 ms | Cold: 346.7 ms<br>Warm: **322.0 ms** | ⚡ **7.1x faster** (~1.98 s saved / turn) |
| **`iam_backend` — `README.md`** | Cold: 224.0 ms<br>Warm: 206.7 ms | Cold: 60.1 ms<br>Warm: **55.8 ms** | 🚀 **3.7x faster** (~151 ms saved / turn) |
| **`iam_backend` — `manage.py`** | Cold: 311.4 ms<br>Warm: 311.3 ms | Cold: 237.4 ms<br>Warm: **229.0 ms** | ⚡ **1.4x faster** (~82 ms saved / turn) |

---

### 2026-08-31 11:02:59 CEST — Cross-Project Real-World Benchmark (`space` & `iam_backend`)

* **Repositories:** `space` (Godot / GDScript / C++), `iam_backend` (Django / Python)
* **Objective:** Evaluate `ulguard post-edit` with targeted file path forwarding (`gdlint <path>`, `clang-format -i <path>`) against legacy multi-second wrapper scripts (`bash run.sh post_edit.py`).
* **Findings:** Path targeting in `gdlint` avoids traversing deep worktree caches. `space` saves ~2.3 seconds on every markdown edit and ~2.0 seconds on every GDScript edit.

| Project & File | Legacy Project Hook | `ulguard post-edit` (Targeted) | Metric / Speedup |
| :--- | :---: | :---: | :---: |
| **`space` — `SPEC.md`** | Warm: 2,339.4 ms | Warm: **30.4 ms** | 🚀 **77.0x faster** (~2,309 ms saved) |
| **`space` — `plugin.gd`** | Warm: 2,387.1 ms | Warm: **330.1 ms** | ⚡ **7.2x faster** (~2,057 ms saved) |
| **`iam_backend` — `README.md`** | Warm: 110.4 ms | Warm: **34.2 ms** | 🚀 **3.2x faster** (~76 ms saved) |
| **`iam_backend` — `manage.py`** | Warm: 218.2 ms *(Ruff only)* | Warm: **232.4 ms** *(Ruff + dmypy)* | 🛡️ Full static type checking added |

---

### 2026-08-31 10:48:38 CEST — Hook Dispatcher: Unconditional Python vs. Go-Native Selective Dispatcher

* **Repository:** `ultraloom`
* **Objective:** Compare Claude Code `PostToolUse` latency when invoking monolithic Python runners versus the lightweight Go-native `ulguard post-edit` dispatcher with selective stack execution and Goroutine parallelism.
* **Findings:** Selective stack execution avoids running irrelevant language tools on documentation edits, reducing latency by **8x**. Goroutine parallelism saves ~38 ms on Python edits.

| Scenario / File | Unconditional Python Runner | Go-Native `ulguard post-edit` | Metric / Speedup |
| :--- | :---: | :---: | :---: |
| **Documentation Edit (`.md`)** | Cold: 9,931.2 ms<br>Warm: 250.4 ms | Cold: 136.2 ms<br>Warm: **31.5 ms** | 🚀 **8.0x faster**<br>(~218.9 ms saved per edit turn) |
| **Python Code Edit (`.py`)** | Sequential: 275.1 ms (warm) | Parallel Goroutines: **237.5 ms** (warm) | ⚡ **~37.6 ms saved per turn** |
