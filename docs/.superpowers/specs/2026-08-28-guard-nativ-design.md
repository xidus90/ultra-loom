# Nativer Policy-Guard (P5) — Entwurf

Stand: 2026-08-28. Status: zur Durchsicht.

## Warum

Der Policy-Hook (`PreToolUse`) feuert bei jedem einzelnen Toolaufruf des LLMs/Agenten (`Write`, `Edit`, `NotebookEdit`, `Bash`, `PowerShell`).

Die Messungen zeigten:
- Der bisherige Python-Aufruf (`uv run ... ultraloom policy hook`) benötigt **~299 ms** je Aufruf (Python-Startup + TOML-Parser + Regex-Engine).
- Bei 200 Tool-Aufrufen je Sitzung summiert sich dies auf **eine Minute reine Hook-Wartezeit**.

In P5 wird der Policy-Guard als eigenständiges, ultrakompaktes Go-Binary **`ultraloom-guard`** (`cmd/guard/`) umgesetzt:
- Startzeit: **< 15 ms**
- Liest die Hook-Payload von `stdin` (JSON)
- Liest `.ultraloom/policy.toml`
- Prüft `protected_paths` (Glob-Pattern) bei Datei-Editoren (`Write`, `Edit`, `NotebookEdit`)
- Prüft `forbidden_commands` (Regex-Pattern) bei Shell-Befehlen (`Bash`, `PowerShell`)
- Beendet bei Regelverletzung mit Exit-Code 2 und Fehlertext auf `stderr`, andernfalls Exit-Code 0.

---

## Was gebaut wird

### 1. `cmd/guard/`
Kompaktes Go-CLI-Binary:
- Liest das optionale Flag `--root <dir>` (Standard `.`).
- Parst `.ultraloom/policy.toml` (unter Verwendung von `internal/tomlstr` bzw. BurntSushi TOML-Parser).
- Liest den Claude Code / Agent Hook-Payload von `stdin`:
  ```json
  {
    "tool_name": "Edit",
    "tool_input": {
      "file_path": "migrations/0001_initial.py"
    }
  }
  ```
  bzw. für Bash:
  ```json
  {
    "tool_name": "Bash",
    "tool_input": {
      "command": "git push origin main"
    }
  }
  ```

### 2. Matching-Logik
- **Dateipfade:** Relative Normalisierung zum `--root`-Pfad; Glob-Matching gegen `protected_paths`.
- **Befehle:** Regex-Matching gegen `forbidden_commands`.
- **Exit Codes:**
  - `0`: Erlaubt.
  - `2`: Blockiert (mit Grund auf `stderr`).
  - `1`: Interner Fehler / unlesbares JSON / fehlende Konfiguration.

### 3. Hook-Konfiguration in `cmd/init/run.go`
- `PreToolUse`-Hook wird konfiguriert für direkten Aufruf von `ultraloom-guard` (bzw. Shim/Binary), mit Fallback auf Python, wenn das Binary noch nicht gebaut ist.
- Timeout von 10s bleibt bestehen (wird jedoch in < 15ms beendet).

---

## Verifikationsplan

1. Unit-Tests für `cmd/guard` in Go (`go test ./cmd/guard` mit 100% Statement Coverage).
2. Benchmarks / Latenz-Verifikation (< 15 ms).
3. Integration in die Gate-Prüfung (`uv run ultraloom check all`).
