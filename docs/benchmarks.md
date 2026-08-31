# Performance Benchmarks

[Deutsche Version](benchmarks.de.md)

## Current Benchmark Summary (Quick Reference)

The table below summarizes the latest performance measurements across projects, toolchains, and lifecycle events, comparing unoptimized baseline execution against the UltraLoom native architecture.

| Project | Target / File Type | Invoked Toolchain | Baseline (No Loom / Legacy) | Optimized (UltraLoom) | Speedup / Savings (Warm) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **`space`** | Markdown Doc (`SPEC.md`) | `ulguard post-edit` (Instant Exit) | Cold: 2,447.2 ms<br>Warm: 2,305.7 ms | Cold: 143.7 ms<br>Warm: **27.6 ms** | 🚀 **83.4x faster**<br>(~2.28 s saved / turn) |
| **`space`** | GDScript Code (`plugin.gd`) | `ulguard post-edit` (`gdlint <file>`) | Cold: 2,344.2 ms<br>Warm: 2,300.3 ms | Cold: 346.7 ms<br>Warm: **322.0 ms** | ⚡ **7.1x faster**<br>(~1.98 s saved / turn) |
| **`iam_backend`** | Markdown Doc (`README.md`) | `ulguard` + `ulguard post-edit` | Cold: 224.0 ms<br>Warm: 206.7 ms | Cold: 60.1 ms<br>Warm: **55.8 ms** | 🚀 **3.7x faster**<br>(~151 ms saved / turn) |
| **`iam_backend`** | Python Code (`manage.py`) | `ulguard` + `ulguard post-edit` (`ruff` + `dmypy` parallel) | Cold: 311.4 ms<br>Warm: 311.3 ms *(Ruff only)* | Cold: 237.4 ms<br>Warm: **229.0 ms** | ⚡ **1.4x faster**<br>(+ full static type check) |
| **`iam_frontend`** | TypeScript Code (`App.tsx`) | `ulguard post-edit` (`eslint` + `tsc` parallel) | Cold: 12,450.0 ms<br>Warm: 11,200.0 ms *(Sequential)* | Cold: 7,614.7 ms<br>Warm: **7,110.9 ms** | ⚡ **1.6x faster**<br>(Parallel ESLint 9 + full tsc) |
| **`iam_frontend`** | Markdown Doc (`README.md`) | `ulguard` + `ulguard post-edit` | Cold: 215.0 ms<br>Warm: 195.0 ms | Cold: 58.2 ms<br>Warm: **28.8 ms** | 🚀 **6.8x faster**<br>(Instant bypass) |
| **`ultra-brain`** | Wiki Doc Edit (`wiki/index.md`) | `ulguard post-edit` (`brain lint <file>`) | Cold: 924.3 ms<br>Warm: 736.4 ms *(Full sweep)* | Cold: 31.7 ms<br>Warm: **29.8 ms** | ⚡ **24.7x faster**<br>(~706 ms saved / turn) |
| **`iam_backend` / `space`** | Session End Wiki Gate | Stop hook (`brain wiki-gate`) | Cold: 152.6 ms<br>Warm: 146.7 ms *(Git only)* | Cold: 1,052.5 ms<br>Warm: **967.1 ms** | 🛡️ **Full OKF bundle lint**<br>+ Git drift verification |

---

## Chronological Benchmark Log

### 2026-08-31 16:46:36 CEST — Two-Tier Wiki Verification: Post-Edit vs. Stop Gate

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
