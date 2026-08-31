# Performance-Benchmarks

[English Version](benchmarks.md)

Dieses Dokument protokolliert alle Performance-Benchmarks, Latenzmessungen und Geschwindigkeitsvergleiche über Repositories und Hook-Lebenszyklen hinweg in chronologischer Reihenfolge.

---

## 31.08.2026 10:48:38 MESZ — Hook-Dispatcher: Unbedingter Python-Start vs. Go-nativer selektiver Dispatcher

* **Repository:** `ultraloom`
* **Ziel:** Vergleich der Latenz von Claude Code `PostToolUse` bei monolithischen Python-Runnern gegenüber dem leichtgewichtigen Go-nativen `ulguard post-edit`-Dispatcher mit selektiver Stack-Ausführung und Goroutine-Parallelität.
* **Ergebnisse:** Die selektive Stack-Ausführung verhindert die Ausführung irrelevanter Sprach-Tools bei Dokumentations-Edits und reduziert die Latenz um das **8-Fache**. Goroutine-Parallelität spart ~38 ms bei Python-Edits.

| Szenario / Datei | Unbedingter Python-Runner | Go-nativ `ulguard post-edit` | Metrik / Beschleunigung |
| :--- | :---: | :---: | :---: |
| **Dokumentations-Edit (`.md`)** | Kalt: 9.931,2 ms<br>Warm: 250,4 ms | Kalt: 136,2 ms<br>Warm: **31,5 ms** | 🚀 **8,0x schneller**<br>(~218,9 ms Ersparnis pro Turn) |
| **Python-Code-Edit (`.py`)** | Sequentiell: 275,1 ms (warm) | Parallele Goroutinen: **237,5 ms** (warm) | ⚡ **~37,6 ms Ersparnis pro Turn** |

---

## 31.08.2026 11:02:59 MESZ — Praxis-Benchmark über mehrere Projekte (`space` & `iam_backend`)

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

## 31.08.2026 14:58:26 MESZ — Bereinigte `install_loom`-Branches (Kompletter Edit-Turn Lifecycle)

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

## 31.08.2026 16:36:30 MESZ — Stop-Hook Wiki Gate: Alt vs. Domänen-natives `brain wiki-gate`

* **Repositories:** `iam_backend` (Nachbar-Wiki `iam_wiki`), `space` (Lokales Wiki `wiki/`)
* **Ziel:** Vergleich des alten reinen Git-Skripts `wiki_gate.py` mit `ultra-brain` nativem `brain wiki-gate` (Git-Drift-Erkennung + vollständiges strukturelles OKF-Bundle-Linting).
* **Ergebnisse:** `brain wiki-gate` schließt umfassende Konzept-, Frontmatter- und Link-Validierungen über das gesamte Wiki-Bundle in ~1,0 s beim Session-Abschluss ab.

| Modus / Projekt | Altes `wiki_gate.py` (nur Git-Commit) | `brain wiki-gate` (Drift + Voller OKF-Check) |
| :--- | :---: | :---: |
| **`iam_backend` (`iam_wiki`)** | Kalt: 152,6 ms<br>Warm: 146,7 ms | Kalt: 1.088,5 ms<br>Warm: **1.128,4 ms** |
| **`space` (`wiki/`)** | *N/A (manuelle Skripte)* | Kalt: 1.050,2 ms<br>Warm: **1.115,7 ms** |

---

## 31.08.2026 16:46:36 MESZ — Zweistufige Wiki-Prüfung: Post-Edit vs. Stop-Gate

* **Repositories:** `ultra-brain`, `ultraloom`
* **Ziel:** Validierung der zweistufigen Prüf-Architektur: Schnelles Einzeldatei-Linting bei Dateispeicherung (`PostToolUse`) gegenüber vollständiger Bundle-Drift- und Link-Validierung am Session-Ende (`Stop`).
* **Ergebnisse:** Die Post-Edit-Einzeldateiprüfung läuft in **~29,8 ms**. Nicht-Wiki Markdown-Edits beenden sofort mit **33,0 ms** Warm-Latenz. Die vollständige Bundle-Validierung am Session-Ende benötigt **~967,1 ms**.

| Prüfstufe | Aufruf-Event | Kalt-Latenz | Warm-Latenz | Umfang |
| :--- | :--- | :---: | :---: | :--- |
| **Stufe 1: Post-Edit (Default / Wiki AUS)** | `PostToolUse` (`README.md`) | 150,5 ms | **33,0 ms** | Sofortiger Exit ohne Kindprozesse |
| **Stufe 1: Post-Edit (Wiki AKTIV)** | `PostToolUse` (`wiki/index.md`) | 31,7 ms | **29,8 ms** | Schnelles `brain lint <file>` pro Datei |
| **Stufe 2: Stop-Hook (Ganzes Wiki)** | `Stop`-Hook (`brain wiki-gate`) | 1.052,5 ms | **967,1 ms** | Voller Drift-Check + OKF-Bundle-Check |
