# Dokumentvorlagen (P3) — Entwurf

Stand: 2026-08-28. Status: zur Durchsicht.

## Warum

In P1 und P2 erzeugt der Installer die Konfigurationsdateien (`answers.toml`, `config.toml`, `installed.toml`, `policy.toml`) und Hooks in `.claude/settings.json`.

Für ein vollständiges Projekt-Setup fehlen noch die grundlegenden Dokumentations- und Instruktionsdateien:
1. **`AGENTS.md`** — Allgemeine Regeln für alle LLMs/Agenten (Sprachen, Commits ohne Model-Credits, Hook-Tools/Shims, Worktree-Regeln).
2. **`CLAUDE.md`** — Claude-spezifische Instruktionen (Referenziert `@AGENTS.md`, enthält Claude Code Besonderheiten).
3. **`GEMINI.md`** — Gemini/Antigravity-spezifische Instruktionen (wenn `gemini` in `agents`).
4. **OKF-Richtlinientext** — Für Projekte mit Brain-Wiki (`gates.wiki.mode == "brain"`).

---

## Was gebaut wird

### 1. Template für `AGENTS.md` (`templates/AGENTS.md.tmpl`)
- **Sprachregeln:**
  - Code/Comments/Commits in `commit_language` (Standard `en`).
  - Doku bilingual oder in `docs_language` (Standard `de` / `en`).
- **Commit-Regeln:**
  - Nutzer als Author/Committer, keine `Co-Authored-By` Credits für Modelle/Subagents.
- **Hook Tools & Shims:**
  - "Whenever a tool invoked by a hook can be executed as a shim pinned to a specific version, it must be used that way."

### 2. Template für `CLAUDE.md` (`templates/CLAUDE.md.tmpl`)
- Startet mit `@AGENTS.md`.
- Enthält Claude Code spezifische Verhaltensregeln (Worktrees, Subagenten, Git-Prüfung vor Commit).

### 3. Template für `GEMINI.md` (`templates/GEMINI.md.tmpl`)
- Referenziert oder enthält die Projekt-Regeln für Google Antigravity / Gemini CLI.

### 4. Integration in `internal/render` & `cmd/init`
- Die Vorlagen werden in `internal/render` als Templates gerendert.
- Wenn `AGENTS.md` oder `CLAUDE.md` im Zielprojekt bereits existieren, werden sie geschützt (Standardverhalten: existierende Dateien gehören dem Projekt und werden nicht überschrieben).
- Nur wenn die Dateien fehlen, werden sie durch `ulinit` erzeugt.
