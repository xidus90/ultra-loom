@AGENTS.md

# For Claude Code only

## Worktrees

A directory under `.claude/worktrees/` is **not** necessarily a git worktree,
and `.git/info/exclude` covers the whole path. Working there means sharing the
index and HEAD with the main checkout: `git status` answers empty and `git add`
skips new files without a word. So read `git rev-parse --git-dir
--git-common-dir` before committing — if the two are equal, it is not a
worktree. Real ones are what `git worktree add` creates under `.worktrees/`,
where the existing ones are.

## Subagents

No subagent pushes. A run may commit; whether those commits reach the remote is
a human's decision. This is here because it has already happened — an
implementer subagent pushed `master` to `origin` without being asked, and its
report did not mention it. After a subagent run, read `git ls-remote origin
<branch>` rather than believing the report.
