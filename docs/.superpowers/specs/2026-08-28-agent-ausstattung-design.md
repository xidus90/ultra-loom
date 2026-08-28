# `.claude`- & `.agents`-Ausstattung (P4) — Entwurf

Stand: 2026-08-28. Status: zur Durchsicht.

## Warum

Nachdem P1 (Installer-Kern), P2 (Hook-Bestand & Lifecycle-Reihenfolge) und P3 (Dokumentvorlagen `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) stehen, stattet P4 neue Projekte mit den gemeinsamen **Skills, Workflows und Agent-Instruktionen** aus:

1. **`verify-until-green` Skill & Workflow:**
   - Der Kern-Workflow von ultraloom: Iteratives Reparieren von Linter-, Typecheck- und Test-Fehlern, bis die Prüfkette (`uv run ultraloom check all`) 100% grün ist.
2. **`session-handover` Skill:**
   - Strukturierte Übergabedokumentation bei Sessionsende oder Kontextgrenzen.
3. **Plattform-spezifische Ablageorte:**
   - **Claude Code (`claude` in `agents`):** `.claude/skills/verify-until-green/SKILL.md`, `.claude/skills/session-handover/SKILL.md`.
   - **Gemini / Antigravity (`gemini` in `agents`):** `.agents/skills/verify-until-green/SKILL.md`, `.agents/skills/session-handover/SKILL.md`.

---

## Was gebaut wird

### 1. Embedded Templates für Skills (`internal/render/templates/skills/`)

- **`verify-until-green/SKILL.md`:**
  - Standard-Skill für die autonome Verifikationsschleife.
  - Definiert den 3-Schritte-Zyklus: Prüfen -> Ursache analysieren -> Minimal fixen -> Re-prüfen bis grün.
  - Nutzt `uv run ultraloom check all` als maßgebliches Gate.

- **`session-handover/SKILL.md`:**
  - Standard-Skill für strukturierte Übergaben unter `handovers/`.
  - Format mit Ziel, aktuellem Status, erledigten Punkten, offenen Punkten und Verifikationsergebnissen.

### 2. Rendering in `internal/render/render.go`

In `Render(a answers.Answers, coverageLane bool)`:
- Wenn `"claude"` in `a.Project.Agents`:
  - `.claude/skills/verify-until-green/SKILL.md`
  - `.claude/skills/session-handover/SKILL.md`
- Wenn `"gemini"` in `a.Project.Agents`:
  - `.agents/skills/verify-until-green/SKILL.md`
  - `.agents/skills/session-handover/SKILL.md`

### 3. Dateischutz & Idempotenz

- Über `internal/write` (`write.Prepare` & `write.Commit`) werden existierende Skills im Projekt geschützt und nicht überschrieben (`skipped, already there:`).
- Fehlende Skills werden angelegt.

---

## Verifikationsplan

1. Unit-Tests in `internal/render/render_test.go` für die Skill-Generierung je nach Agenten-Auswahl.
2. Integrationstests in `cmd/init/run_test.go`.
3. End-to-End-Test im `space`-Worktree mit `ulinit.exe`.
4. Vollständiger Gate-Lauf mit `uv run ultraloom check all`.
