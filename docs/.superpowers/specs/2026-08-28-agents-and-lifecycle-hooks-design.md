# Agent-Plattformen & Hook-Lifecycle-Reihenfolge — Entwurf

Stand: 2026-08-28. Status: zur Durchsicht.

## Ziel

1. **Hook-Lifecycle-Reihenfolge:**
   Die generierten Hooks in `.claude/settings.json` werden in der exakten Lifecycle-Reihenfolge der Claude Code Dokumentation hinzugefügt:
   1. `SessionStart` (Init, Session-Start)
   2. `PreToolUse` (Policy-Engine / Guard)
   3. `PostToolUse` (Parallele Tool-Prüfungen: Linter, Typecheck, Formatter je nach Stack)
   4. `SubagentStart` (Subagent-Tracking)
   5. `SubagentStop` (Subagent-Cleanup)
   6. `Stop` (Quality Gate / Verifikation)

2. **Agenten-Plattform-Auswahl im Installer (`ulinit`):**
   Der Installer unterstützt die Auswahl der Ziel-Agenten:
   - Standard: `claude,gemini` (beide Plattformen werden konfiguriert)
   - Optionen: `claude`, `gemini`, `claude,gemini` / `all`
   - CLI-Flag: `--agents`
   - `[project].agents` in `answers.toml` und `config.toml`

---

## Architektur-Anpassungen

### 1. `internal/answers`
- `answers.Project` erhält `Agents []string `toml:"agents"`
- `Defaults` setzt `Agents: []string{"claude", "gemini"}`

### 2. `internal/interview`
- Frage für `agents` mit Default `claude, gemini` und Flag `--agents`.

### 3. `cmd/init/run.go`
- `hookEntries` baut die Hooks in der dokumentierten Lifecycle-Reihenfolge:
  1. `SessionStart`
  2. `PreToolUse`
  3. `PostToolUse`
  4. `SubagentStart` (wenn `HasGit`)
  5. `SubagentStop` (wenn `HasGit`)
  6. `Stop` (Gate + optionaler Wiki-Hook)
- Hook-Erzeugung wird bedingt ausgeführt, wenn `"claude"` in `filled.Project.Agents` enthalten ist.
- Flag `--agents` verarbeitet `applyFlags`.

### 4. `internal/settings`
- Sortierung der Events bei der Ausgabe in `Merge`, sodass die Lifecycle-Reihenfolge in `.claude/settings.json` gewahrt bleibt.
