# Hook-Bestand (P2) — Entwurf

Stand: 2026-08-28. Status: zur Durchsicht.

## Warum

In P1 erzeugte der Installer für `PostToolUse` einen einzelnen, monolithischen Hook:
`uv run --project ... ultraloom hook post-edit`.

Die Messungen vom 2026-08-27/28 zeigten jedoch:
- `ultraloom hook post-edit` benötigt **685 ms** (Python-Start 160 ms + Importe + sequentielle Ausführung).
- Dieselben Werkzeuge direkt aufgerufen benötigen **232 ms parallel** (bzw. 267 ms sequentiell).
- `ruff check .` als Rust-Binary benötigt nur **20–27 ms**.

### Ausführungs-Hierarchie (von schnell nach langsam)

1. **`uv tool + gepinnter Shim`** (~10–30 ms): Direkter Aufruf des Binär-Shims im Toolchain-Pfad. Kein Spawn-Overhead, kein Wrapper.
2. **`uvx <tool>@<version>`** (~30–80 ms): Direkt über `uvx` mit gepinnter Version ausgeführt.
3. **`uv run --with <tool>@<version>`** (~80–150 ms): Ephemeres Environment für den Toolaufruf.
4. **`ultraloom (gepinnt)`** (~300 ms): Ultraloom als gepinnter CLI-Aufruf.
5. **`ultraloom (monolithisch)`** (~685 ms): Python-Harness mit sequentieller Wrapper-Ausführung.

**Grundsatz für Hook-Generierung:** Wann immer ein Werkzeug als gepinnter Shim oder nativer Binary-Aufruf existiert, wird der höchstmögliche Tier dieser Hierarchie gewählt.

---

## Was gebaut wird

1. **Stack-spezifische Tool-Definitionen für `PostToolUse`:**
   Je nach erkannten Stacks (`detect.Facts.Stacks`) generiert `init` direkte Hook-Befehle:
   - **Python:**
     - `ruff`: `uv run ruff check --output-format=concise .` (Timeout: 15s)
     - `dmypy`: `uv run dmypy run -- --no-error-summary --no-pretty` (Timeout: 30s)
   - **GDScript / Godot:**
     - `gdlint`: `uvx gdlint .` (Timeout: 15s)
   - **C# / .NET:**
     - `dotnet format`: `dotnet format --verify-no-changes` (Timeout: 30s)
     - `dotnet build`: `dotnet build --no-restore` (Timeout: 45s)
   - **TypeScript / Node:**
     - `eslint`: `npx eslint .` (Timeout: 20s)
     - `tsc`: `npx tsc --noEmit` (Timeout: 30s)
   - **Rust:**
     - `clippy`: `cargo clippy -- -D warnings` (Timeout: 30s)
     - `fmt`: `cargo fmt --check` (Timeout: 15s)
   - **Go:**
     - `govet`: `go vet ./...` (Timeout: 20s)

2. **Parallele Hook-Listen in `.claude/settings.json`:**
   Claude Code unterstützt in `hooks[event]` mehrere Blöcke oder in einem Block mehrere Befehle.
   Jedes Werkzeug erhält einen eigenständigen Block mit `"ultraloomOwned": true` und passendem `matcher: "Write|Edit|NotebookEdit"`.

3. **Stop-Gate:**
   - Standard-Prüfkette: `uv run ultraloom check all --root "${CLAUDE_PROJECT_DIR}"` (Timeout: 300s).
   - Bei `wiki.mode = "brain"`: Zusätzlicher Stop-Hook `brain lint` (Timeout: 120s).

4. **PreToolUse (Policy):**
   - `uv run ultraloom policy hook --root "${CLAUDE_PROJECT_DIR}"` (Timeout: 10s, Matcher: `Write|Edit|NotebookEdit|Bash|PowerShell`).

5. **Session- & Subagent-Tracking:**
   - `SessionStart`: `uv run ultraloom hook session-start` (Timeout: 20s)
   - `SubagentStart`: `uv run ultraloom hook subagent-start` (Timeout: 30s)
   - `SubagentStop`: `uv run ultraloom hook subagent-stop` (Timeout: 30s)

---

## Architektur & Modul-Anpassungen

### `internal/settings` & `internal/render`
- `settings.Entry` bildet einzelne Befehle mit individuellem Timeout, Matcher und Event ab.
- `settings.Merge` unterstützt das Zusammenführen mehrerer `ultraloomOwned`-Einträge unter demselben Event (z. B. 2–3 parallele `PostToolUse`-Einträge).
- `cmd/init/run.go` delegiert die Erzeugung der Hook-Einträge an eine dedizierte Funktion `hookEntries(facts detect.Facts, wikiHooks bool) []settings.Entry`, die stack-spezifisch die direkten Tools zusammenstellt.
