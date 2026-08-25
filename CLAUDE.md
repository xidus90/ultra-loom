@AGENTS.md

# For Claude Code only

## Worktrees

A directory under `.claude/worktrees/` is **not** necessarily a git worktree,
and `.git/info/exclude` covers the whole path. Working there means sharing the
index and HEAD with the main checkout: `git status` answers empty and `git add`
skips new files without a word.

Ask `git rev-parse --show-toplevel`. Does it name the directory you are
standing in? Then it is a tree of its own. Does it name the main checkout? Then
it is not, whatever the path suggests. `git worktree list` is the same answer
from the other side: a directory that is not in that list is not a worktree.

Do **not** compare `--git-dir` against `--git-common-dir`. This page said to
until 2026-08-25, and the test does not work: from
`.claude/worktrees/opus-5-enforcement-57de82` git answers
`C:/Users/micro/Documents/#GIT/ultraloom/.git` for the first and `../../../.git`
for the second — the same directory written two ways. Compared as text they
differ, so the rule says "worktree" about a directory that shares the index.

Real worktrees are what `git worktree add` creates. This repository has them in
both places — `.worktrees/multi-provider-llm` and
`.claude/worktrees/project-history-planning-cf98dc` — so the path is no
evidence either way.

## Before every commit

Read `git diff --cached --stat` and look at what is actually staged. On
2026-08-25 a commit here carried five file renames that belonged to another
session working in the same checkout: `git add <my file>` was correct, but the
index already held someone else's work. Reading the branch and HEAD catches the
case where a foreign session *empties* the index; this catches the case where it
*leaves something behind*.

## Subagents

No subagent pushes. A run may commit; whether those commits reach the remote is
a human's decision. This is here because it has already happened — an
implementer subagent pushed `master` to `origin` without being asked, and its
report did not mention it. After a subagent run, read `git ls-remote origin
<branch>` rather than believing the report.
