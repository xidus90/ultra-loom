# Tooling-Check, PATH-Auflösung & Tool-Installation — Entwurf

Stand: 2026-08-28. Status: zur Durchsicht.

## Warum

Bisher ging der Installer davon aus, dass Werkzeuge entweder global auf `$PATH` liegen oder über Standard-Wrapper (`uvx`, `npx`, `dotnet`) aufgerufen werden. Wenn ein Tool nicht auf `$PATH` liegt, schlagen Hooks fehl.

Gemäß den Anforderungen:
1. **$PATH-Prüfung:** Der Installer prüft für alle erkannten Stacks, ob die benötigten Werkzeuge auf `$PATH` auflösbar sind (`exec.LookPath`).
2. **Benutzerabfrage bei fehlendem Tool:** Wird ein Werkzeug nicht auf `$PATH` gefunden:
   - Der Benutzer wird im interaktiven Interview gefragt:
     a) Entweder nach einem manuellen Pfad zum Werkzeug.
     b) Oder ob das Tool automatisch installiert werden soll (z. B. `uv tool install ruff`, `uv tool install gdtoolkit`, etc.).
3. **Precommit-Installation mit voller Suite:**
   - Git-Precommit-Hook (`.githooks/pre-commit` oder `.git/hooks/pre-commit`) wird installiert.
   - Profil `precommit` in `.ultraloom/config.toml` führt die volle Suite aus (`["lint", "types", "test", "coverage"]`).

---

## Was gebaut wird

### 1. Tooling-Prüfung (`internal/tooling/`)
- Prüft Werkzeuge nach erkanntem Stack:
  - `python`: `uv`, `ruff`, `dmypy`/`mypy`, `pytest`
  - `gdscript`: `gdlint` (`gdtoolkit`), `godot`
  - `csharp`: `dotnet`
  - `typescript`: `npm`/`npx`, `eslint`, `tsc`
  - `rust`: `cargo`
  - `go`: `go`, `gofmt`
- Status je Tool: `Found(path)` oder `Missing`.

### 2. Interview & Pfad-Abfrage (`internal/interview/`)
- Für jedes fehlende Werkzeug:
  - Frage: Tool nicht auf PATH gefunden. Optionen:
    1. Pfad manuell eingeben.
    2. Automatisch installieren (sofern Installer/Manager wie `uv`, `npm` etc. vorhanden).
    3. Überspringen (Warnung im Report).

### 3. Precommit-Hook Installation (`cmd/init/run.go`)
- Schreibt `.githooks/pre-commit` mit voller Suite (`uv run ultraloom check precommit`).
- Konfiguriert `git config core.hooksPath .githooks`.
- Schützt bestehende `.githooks/pre-commit`-Dateien.
