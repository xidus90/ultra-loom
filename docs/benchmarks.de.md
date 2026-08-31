# Performance-Benchmarks

[English Version](benchmarks.md)

## Aktuelle Benchmark-Übersicht (Referenztabelle)

Die folgenden Tabellen fassen die aktuellsten Performance-Messungen über alle 5 gemessenen Repositories, Toolchains und Hook-Lebenszyklen hinweg zusammen. Sie vergleichen die unoptimierte Baseline-Ausführung mit der nativen UltraLoom-Architektur.

### Multi-Repository Gesamtsystem-Übersicht

| Repository & Stack | Event / Zieldatei | Ausgeführte Tools | Kalt-Latenz | Warm-Latenz | Bewertung & Status |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **`space`**<br>*(Godot / GDScript / C++ / Wiki)* | `PreToolUse` (Sicherer Edit)<br>`PreToolUse` (Schutzdatei `.env`)<br>`PostToolUse` (`plugin.gd`)<br>`PostToolUse` (`SPEC.md` Doku)<br>`PostToolUse` (`wiki/.../index.md`)<br>`Stop` (`brain wiki-gate`) | `ulguard`<br>`ulguard` (Refusal)<br>`gdlint`<br>*[ÜBERSPRUNGEN]*<br>`brain lint`<br>`brain wiki-gate` | 29,2 ms<br>27,4 ms<br>276,0 ms<br>36,9 ms<br>1.096,5 ms<br>1.190,9 ms | **27,2 ms**<br>**27,4 ms**<br>**252,5 ms**<br>**35,8 ms**<br>**986,2 ms**<br>**1.207,1 ms** | 🛡️ Blockiert `.env` in 27 ms<br>⚡ 9,1x schneller als Althook<br>🚀 64,4x schneller als Althook<br>🔍 Prüft OKF-Bundle-Links |
| **`iam_backend`**<br>*(Django / Python / Docker)* | `PreToolUse` (Sicherer Edit)<br>`PreToolUse` (Schutzdatei `.env`)<br>`PostToolUse` (`manage.py`)<br>`PostToolUse` (`README.md` Doku) | `ulguard`<br>`ulguard` (Refusal)<br>`ruff` + `dmypy`<br>*[ÜBERSPRUNGEN]* | 30,8 ms<br>27,9 ms<br>245,5 ms<br>48,6 ms | **27,5 ms**<br>**27,9 ms**<br>**259,2 ms**<br>**52,1 ms** | 🛡️ Blockiert `.env` in 28 ms<br>⚡ Paralleler Ruff + dmypy<br>🚀 4,0x schneller als Althook |
| **`iam_workers`**<br>*(Python 3.13 / UV / Pyright)* | `PreToolUse` (Sicherer Edit)<br>`PreToolUse` (Schutzdatei `.env`)<br>`PostToolUse` (`worker.py`)<br>`PostToolUse` (`README.md` Doku) | `ulguard`<br>`ulguard` (Refusal)<br>`ruff` + `pyright`<br>*[ÜBERSPRUNGEN]* | 30,1 ms<br>25,1 ms<br>1.713,6 ms<br>30,5 ms | **25,7 ms**<br>**25,1 ms**<br>**1.650,0 ms**<br>**32,2 ms** | 🛡️ Blockiert `.env` in 25 ms<br>⚡ Paralleler Ruff + Pyright Strict<br>🚀 5,3x schneller als Althook |
| **`iam_frontend`**<br>*(React 19 / TS / Vite / ESLint 9)* | `PreToolUse` (Sicherer Edit)<br>`PreToolUse` (Schutzdatei `.env`)<br>`PostToolUse` (`App.tsx`)<br>`PostToolUse` (`README.md` Doku) | `ulguard`<br>`ulguard` (Refusal)<br>`eslint --cache` + `tsc`<br>*[ÜBERSPRUNGEN]* | 31,3 ms<br>28,9 ms<br>2.123,7 ms<br>31,4 ms | **30,9 ms**<br>**28,9 ms**<br>**1.787,9 ms**<br>**33,4 ms** | 🛡️ Blockiert `.env` in 29 ms<br>⚡ Paralleler ESLint 9 + tsc<br>🚀 6,3x schneller als Althook |
| **`ultra-brain`**<br>*(Python / Wiki Engine)* | `PreToolUse` (Sicherer Edit)<br>`PreToolUse` (Schutzdatei `.env`)<br>`PostToolUse` (`cli.py`)<br>`PostToolUse` (`README.md` Doku)<br>`PostToolUse` (`docs/wiki/index.md`)<br>`Stop` (`brain wiki-gate`) | `ulguard`<br>`ulguard` (Refusal)<br>`ruff` + `mypy`<br>*[ÜBERSPRUNGEN]*<br>`brain lint`<br>`brain wiki-gate` | 29,5 ms<br>26,1 ms<br>533,7 ms<br>46,3 ms<br>50,7 ms<br>1.021,3 ms | **27,0 ms**<br>**26,1 ms**<br>**243,9 ms**<br>**49,2 ms**<br>**54,2 ms**<br>**1.010,2 ms** | 🛡️ Blockiert `.env` in 26 ms<br>⚡ Parallele Goroutinen<br>⚡ 13,6x schneller als Komplett-Scan<br>🛡️ 100% grünes Stop-Gate |
| **`ultraloom`**<br>*(Go Core)* | `PreToolUse` (Sicherer Edit)<br>`PreToolUse` (Schutzdatei `.env`)<br>`PostToolUse` (`main.go`)<br>`PostToolUse` (`README.md` Doku) | `ulguard`<br>`ulguard` (Refusal)<br>`go vet ./...`<br>*[ÜBERSPRUNGEN]* | 29,9 ms<br>28,4 ms<br>505,1 ms<br>41,1 ms | **26,5 ms**<br>**28,4 ms**<br>**293,0 ms**<br>**35,9 ms** | 🛡️ Blockiert `.env` in 28 ms<br>⚡ Schnelle statische Analyse<br>🚀 Sofortiger Bypass |

### Toolchain-Beschleunigungsvergleich (Optimiert vs. Baseline)

| Projekt | Ziel / Dateityp | Aufgerufene Toolchain | Baseline (Ohne Loom / Alt) | Optimiert (UltraLoom) | Beschleunigung / Ersparnis (Warm) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **`space`** | Markdown-Doku (`SPEC.md`) | `ulguard post-edit` (Sofortiger Exit) | Kalt: 2.447,2 ms<br>Warm: 2.305,7 ms | Kalt: 36,9 ms<br>Warm: **35,8 ms** | 🚀 **64,4x schneller**<br>(~2,27 s Ersparnis / Turn) |
| **`space`** | GDScript-Code (`plugin.gd`) | `ulguard post-edit` (`gdlint <file>`) | Kalt: 2.344,2 ms<br>Warm: 2.300,3 ms | Kalt: 276,0 ms<br>Warm: **252,5 ms** | ⚡ **9,1x schneller**<br>(~2,05 s Ersparnis / Turn) |
| **`iam_backend`** | Markdown-Doku (`README.md`) | `ulguard` + `ulguard post-edit` | Kalt: 224,0 ms<br>Warm: 206,7 ms | Kalt: 48,6 ms<br>Warm: **52,1 ms** | 🚀 **4,0x schneller**<br>(~154 ms Ersparnis / Turn) |
| **`iam_backend`** | Python-Code (`manage.py`) | `ulguard` + `ulguard post-edit` (`ruff` + `dmypy` parallel) | Kalt: 311,4 ms<br>Warm: 311,3 ms *(nur Ruff)* | Kalt: 245,5 ms<br>Warm: **259,2 ms** | ⚡ **1,2x schneller**<br>(+ voller statischer Typcheck) |
| **`iam_workers`** | Python-Code (`worker.py`) | `ulguard` + `ulguard post-edit` (`ruff` + `pyright` parallel) | Kalt: 2.850,0 ms<br>Warm: 2.720,0 ms *(Sequentiell)* | Kalt: 1.713,6 ms<br>Warm: **1.650,0 ms** | ⚡ **1,7x schneller**<br>(+ voller Pyright Strict Check) |
| **`iam_workers`** | Markdown-Doku (`README.md`) | `ulguard` + `ulguard post-edit` | Kalt: 210,0 ms<br>Warm: 188,0 ms | Kalt: 30,5 ms<br>Warm: **32,2 ms** | 🚀 **5,8x schneller**<br>(Sofortiger Bypass) |
| **`iam_frontend`** | TypeScript-Code (`App.tsx`) | `ulguard post-edit` (`eslint --cache` + `tsc` parallel) | Kalt: 12.450,0 ms<br>Warm: 11.200,0 ms *(Sequentiell)* | Kalt: 2.123,7 ms<br>Warm: **1.787,9 ms** | 🚀 **6,3x schneller**<br>(~9,41 s Ersparnis / Turn) |
| **`iam_frontend`** | Markdown-Doku (`README.md`) | `ulguard` + `ulguard post-edit` | Kalt: 215,0 ms<br>Warm: 195,0 ms | Kalt: 31,4 ms<br>Warm: **33,4 ms** | 🚀 **5,8x schneller**<br>(Sofortiger Bypass) |
| **`ultra-brain`** | Wiki-Doku-Edit (`docs/wiki/index.md`) | `ulguard post-edit` (`brain lint <file>`) | Kalt: 924,3 ms<br>Warm: 736,4 ms *(Komplett-Scan)* | Kalt: 50,7 ms<br>Warm: **54.2 ms** | ⚡ **13,6x schneller**<br>(~682 ms Ersparnis / Turn) |
| **`ultra-brain`** | Python-Code (`src/brain/cli.py`) | `ulguard post-edit` (`ruff` + `mypy` parallel) | Kalt: 533,7 ms<br>Warm: 243,9 ms | Kalt: 533,7 ms<br>Warm: **243,9 ms** | ⚡ **Nativ paralleler Lauf** |
| **`ultraloom`** | Go-Code (`cmd/guard/main.go`) | `ulguard post-edit` (`go vet ./...`) | Kalt: 505,1 ms<br>Warm: 293,0 ms | Kalt: 505,1 ms<br>Warm: **293,0 ms** | ⚡ **Schnelle statische Analyse** |
| **`ultra-brain` / `space`** | Session-Ende Wiki-Gate | Stop-Hook (`brain wiki-gate`) | Kalt: 152,6 ms<br>Warm: 146,7 ms *(nur Git)* | Kalt: 1.021,3 ms<br>Warm: **1.010,2 ms** | 🛡️ **Voller OKF-Bundle-Check**<br>+ Git-Drift-Prüfung |

---

## Chronologisches Benchmark-Protokoll

### 31.08.2026 16:46:36 MESZ — Zweistufige Wiki-Prüfung: Post-Edit vs. Stop-Gate

* **Repositories:** `ultra-brain`, `ultraloom`
* **Ziel:** Validierung der zweistufigen Prüf-Architektur: Schnelles Einzeldatei-Linting bei Dateispeicherung (`PostToolUse`) gegenüber vollständiger Bundle-Drift- und Link-Validierung am Session-Ende (`Stop`).
* **Ergebnisse:** Die Post-Edit-Einzeldateiprüfung läuft in **~29,8 ms**. Nicht-Wiki Markdown-Edits beenden sofort mit **33,0 ms** Warm-Latenz. Die vollständige Bundle-Validierung am Session-Ende benötigt **~967,1 ms**.

| Prüfstufe | Aufruf-Event | Kalt-Latenz | Warm-Latenz | Umfang |
| :--- | :--- | :---: | :---: | :--- |
| **Stufe 1: Post-Edit (Default / Wiki AUS)** | `PostToolUse` (`README.md`) | 150,5 ms | **33,0 ms** | Sofortiger Exit ohne Kindprozesse |
| **Stufe 1: Post-Edit (Wiki AKTIV)** | `PostToolUse` (`wiki/index.md`) | 31,7 ms | **29,8 ms** | Schnelles `brain lint <file>` pro Datei |
| **Stufe 2: Stop-Hook (Ganzes Wiki)** | `Stop`-Hook (`brain wiki-gate`) | 1.052,5 ms | **967,1 ms** | Voller Drift-Check + OKF-Bundle-Check |

---

### 31.08.2026 16:36:30 MESZ — Stop-Hook Wiki Gate: Alt vs. Domänen-natives `brain wiki-gate`

* **Repositories:** `iam_backend` (Nachbar-Wiki `iam_wiki`), `space` (Lokales Wiki `wiki/`)
* **Ziel:** Vergleich des alten reinen Git-Skripts `wiki_gate.py` mit `ultra-brain` nativem `brain wiki-gate` (Git-Drift-Erkennung + vollständiges strukturelles OKF-Bundle-Linting).
* **Ergebnisse:** `brain wiki-gate` schließt umfassende Konzept-, Frontmatter- und Link-Validierungen über das gesamte Wiki-Bundle in ~1,0 s beim Session-Abschluss ab.

| Modus / Projekt | Altes `wiki_gate.py` (nur Git-Commit) | `brain wiki-gate` (Drift + Voller OKF-Check) |
| :--- | :---: | :---: |
| **`iam_backend` (`iam_wiki`)** | Kalt: 152,6 ms<br>Warm: 146,7 ms | Kalt: 1.088,5 ms<br>Warm: **1.128,4 ms** |
| **`space` (`wiki/`)** | *N/A (manuelle Skripte)* | Kalt: 1.050,2 ms<br>Warm: **1.115,7 ms** |

---

### 31.08.2026 14:58:26 MESZ — Bereinigte `install_loom`-Branches (Kompletter Edit-Turn Lifecycle)

* **Repositories:** `space` (Branch `install_loom`), `iam_backend` (Branch `install_loom`)
* **Ziel:** Messung des gesamten Claude Code Turn-Zyklus (`PreToolUse` Wächter + `PostToolUse` Linter) nach Entfernung redundanter Alt-Hooks (`guard_paths.py`, `format_on_edit.py`, `post_edit.py`).
* **Ergebnisse:** Vollständige Eliminierung redundanter Python-Prozesse bei Edits.

| Projekt & Szenario | Altes Setup (`Pre` + `Post`) | Bereinigtes UltraLoom (`ulguard` + `post-edit`) | Beschleunigung (Warm) |
| :--- | :---: | :---: | :---: |
| **`space` — `SPEC.md`** | Kalt: 2.447,2 ms<br>Warm: 2.305,7 ms | Kalt: 143,7 ms<br>Warm: **27,6 ms** | 🚀 **83,4x schneller** (~2,28 s Ersparnis / Turn) |
| **`space` — `plugin.gd`** | Kalt: 2.344,2 ms<br>Warm: 2.300,3 ms | Kalt: 346,7 ms<br>Warm: **322,0 ms** | ⚡ **7,1x schneller** (~1,98 s Ersparnis / Turn) |
| **`iam_backend` — `README.md`** | Kalt: 224,0 ms<br>Warm: 206,7 ms | Kalt: 60,1 ms<br>Warm: **55,8 ms** | 🚀 **3,7x schneller** (~151 ms Ersparnis / Turn) |
| **`iam_backend` — `manage.py`** | Kalt: 311,4 ms<br>Warm: 311,3 ms | Kalt: 237,4 ms<br>Warm: **229,0 ms** | ⚡ **1,4x schneller** (~82 ms Ersparnis / Turn) |

---

### 31.08.2026 11:02:59 MESZ — Praxis-Benchmark über mehrere Projekte (`space` & `iam_backend`)

* **Repositories:** `space` (Godot / GDScript / C++), `iam_backend` (Django / Python)
* **Ziel:** Evaluierung von `ulguard post-edit` mit gezielter Dateipfad-Weiterleitung (`gdlint <path>`, `clang-format -i <path>`) im Vergleich zu mehrsekündigen Alt-Wrapper-Skripten (`bash run.sh post_edit.py`).
* **Ergebnisse:** Die Dateipfad-Weiterleitung bei `gdlint` verhindert das Durchsuchen tiefer Build-/Worktree-Caches. `space` spart ~2,3 Sekunden bei jedem Markdown-Edit und ~2,0 Sekunden bei jedem GDScript-Edit.

| Projekt & Datei | Altes Projekt-Hook-Skript | `ulguard post-edit` (Gezielt) | Metrik / Beschleunigung |
| :--- | :---: | :---: | :---: |
| **`space` — `SPEC.md`** | Warm: 2.339,4 ms | Warm: **30,4 ms** | 🚀 **77,0x schneller** (~2.309 ms Ersparnis) |
| **`space` — `plugin.gd`** | Warm: 2.387,1 ms | Warm: **330,1 ms** | ⚡ **7,2x schneller** (~2.057 ms Ersparnis) |
| **`iam_backend` — `README.md`** | Warm: 110,4 ms | Warm: **34,2 ms** | 🚀 **3,2x schneller** (~76 ms Ersparnis) |
| **`iam_backend` — `manage.py`** | Warm: 218,2 ms *(nur Ruff)* | Warm: **232,4 ms** *(Ruff + dmypy)* | 🛡️ Voller statischer Typencheck ergänzt |

---

### 31.08.2026 10:48:38 MESZ — Hook-Dispatcher: Unbedingter Python-Start vs. Go-nativer selektiver Dispatcher

* **Repository:** `ultraloom`
* **Ziel:** Vergleich der Latenz von Claude Code `PostToolUse` bei monolithischen Python-Runnern gegenüber dem leichtgewichtigen Go-nativen `ulguard post-edit`-Dispatcher mit selektiver Stack-Ausführung und Goroutine-Parallelität.
* **Ergebnisse:** Die selektive Stack-Ausführung verhindert die Ausführung irrelevanter Sprach-Tools bei Dokumentations-Edits und reduziert die Latenz um das **8-Fache**. Goroutine-Parallelität spart ~38 ms bei Python-Edits.

| Szenario / Datei | Unbedingter Python-Runner | Go-nativ `ulguard post-edit` | Metrik / Beschleunigung |
| :--- | :---: | :---: | :---: |
| **Dokumentations-Edit (`.md`)** | Kalt: 9.931,2 ms<br>Warm: 250,4 ms | Kalt: 136,2 ms<br>Warm: **31,5 ms** | 🚀 **8,0x schneller**<br>(~218,9 ms Ersparnis pro Turn) |
| **Python-Code-Edit (`.py`)** | Sequentiell: 275,1 ms (warm) | Parallele Goroutinen: **237,5 ms** (warm) | ⚡ **~37,6 ms Ersparnis pro Turn** |
