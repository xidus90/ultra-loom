# ultraloom

## Where things live

Specs, plans and SDD live under `docs/.superpowers/`. Flows, each with its
graph picture and an explanation, live under `docs/flows/`.

## Languages

Anything that instructs an LLM is written in English: this file, `CLAUDE.md`,
and whatever lives under `.claude/`. A model reads them on every turn, and a
second language in the file it steers by buys nothing.

So is everything inside a file that is not prose: comments, docstrings, error
messages and commit messages, in source and in configuration alike —
`.ultraloom/config.toml` and `.claude/settings.json` included. The line runs
between prose and everything else, not between one file type and another; a
comment that explains a regex belongs to the code it sits in, whoever wrote it.

The documentation is bilingual instead: the file without a suffix is the
English variant and the standard, the German one carries `.de.md` right beside
it — `README.md` / `README.de.md`, `docs/flows/verify-until-green.md` /
`verify-until-green.de.md`. Each variant links to the other under its heading.

Exempt from both rules are the working papers under `docs/.superpowers/`: specs
and plans are written once, read by a human, and never translated.

## Commits

A commit carries the user as its author and its committer, and nothing in the
message credits a model or an agent — no `Co-Authored-By` line for Claude or
for a subagent. The history says what changed, not which tool held the pen.

## Hook Tools and Shims

Whenever a tool invoked by a hook can be executed as a shim pinned to a specific version, it must be used that way. Direct pinned shims ensure deterministic runs, prevent toolchain drift across machines, and avoid monolithic wrapper overhead.


