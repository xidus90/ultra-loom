@AGENTS.md

# Nur für Claude Code

## Worktrees

Ein Verzeichnis unter `.claude/worktrees/` ist **nicht** zwangsläufig ein
Git-Worktree, und `.git/info/exclude` deckt den ganzen Pfad ab. Wer dort
arbeitet, teilt sich Index und HEAD mit dem Hauptcheckout, `git status`
antwortet leer, und `git add` überspricht neue Dateien wortlos. Vor einem
Commit deshalb `git rev-parse --git-dir --git-common-dir` lesen: sind beide
gleich, ist es kein Worktree. Echte Worktrees legt `git worktree add` unter
`.worktrees/` an — dort stehen die bestehenden.

## Subagenten

Kein Subagent pusht. Ein Lauf darf committen; ob die Commits das Remote
erreichen, entscheidet der Mensch. Das steht hier, weil es schon passiert ist —
ein Implementierungs-Subagent schob `master` nach `origin`, ohne gefragt zu
werden, und der Bericht erwähnte es nicht. Nach Subagentenläufen gilt deshalb:
`git ls-remote origin <zweig>` lesen statt dem Bericht glauben.
