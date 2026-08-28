# Session Handover: Installer core (P1) executed, reviewed and merged to master

**Date & Time:** 2026-08-28 20:19
**Branch / Worktree:** `master` (main checkout `C:/Users/micro/Documents/#GIT/ultraloom`); the feature branch `feat/installer-kern` still exists in the worktree `.worktrees/installer-kern`, one commit behind master
**Status:** Ready for Review — merged locally, **nothing pushed**
**Touched Files:** the branch added the whole Go tree; the two files that matter for what is still open are [.gitattributes](file:///C:/Users/micro/Documents/%23GIT/ultraloom/.gitattributes) and [.ultraloom/config.toml](file:///C:/Users/micro/Documents/%23GIT/ultraloom/.ultraloom/config.toml)

---

## 1. Focus & Active Context

This session finished the installer-core plan: tasks 7–11 plus the three task reviews (4, 5, 6) that the previous session could not deliver, then the whole-branch review, its fix wave, and a fast-forward merge into `master` at the user's request.

The mental model that shaped every dispatch: **the plan's example code is a proposal, its tests are the mandate.** Every single task proved it again — task 6 had four defects in its example, task 7 nine, task 8 four, task 9 seven, task 10 four, and task 11's sketch eleven mismatches against the real packages. None was caught by that task's own mandated tests. Every implementer dispatch carried that warning explicitly, and it paid for itself every time.

The second model, learned expensively: **a rationale the code does not honour is its own defect class.** It was the most frequent finding of the session. Reviewers who check every sentence against the code find them; reviewers who read the code do not.

The ledger with the full task-by-task record and every ruling lives at `.worktrees/installer-kern/.superpowers/sdd/2026-08-28-installer-kern/progress.md`, with a longer German summary beside it in `handover.md`. **Both are gitignored and exist only in that worktree.**

## 2. Key Decisions & Rejected Alternatives

**Decisions made:**

- **The `.mcp.json` plan conflict resolved against the mandated test.** Task 10's mandated test forces the `ULTRA_BRAIN_DIR` path into `Find`'s return value; the global constraint forbids machine paths in versioned files. The constraint won: `internal/brainpath` was left exactly as mandated, and `cmd/init` writes the entry only when brain is found on PATH, printing it for manual insertion otherwise.
- **The missing-`fail_under` case was closed despite crossing a task's file boundary.** A generated project was getting a `[verify.coverage]` lane that nothing could turn red — the precise failure the tool exists to prevent. Both the section *and* the `coverage` entry in the precommit profile now drop, because the Python config loader falls back to a threshold of 100 and the lane would otherwise keep running.
- **The duplicated TOML quoter was extracted** into `internal/tomlstr` after its two copies' comments had already diverged.
- **The final fix wave got a second round**, which the skill does not provide for, because the re-review had *demonstrated* that a junctioned `.claude` put `settings.json` outside the project at exit 0.
- **Reviewers were never given the existing rulings in their prompts** — that would be pre-judging. Several found the rulings in the ledger themselves and confirmed them independently, which is worth more.

**Rejected alternatives and why:**

- **An unexpanded `${ULTRA_BRAIN_DIR}` in `.mcp.json`** — nobody verified against the MCP documentation that clients expand it. Do not retry this without checking the docs first.
- **Test-side line-ending normalisation for the CRLF bug** — rejected because the templates are the *product*, not a fixture. Normalising before comparing would have called a fresh clone green while concealing that the installer writes CRLF configuration onto a user's disk.
- **A repo-wide `* text=auto eol=lf`** — it would have renormalised five files another session is holding uncommitted. The pinning is deliberately narrow.
- **A built-in default vendor URL** — it would turn every plain `init` into a network call in exactly the unattended shape that was just fixed, and there is no tag this repo could honestly pin a stranger to.
- **`os.SameFile` against `os.DevNull` instead of `golang.org/x/term`** — it patches one case and lets every other character device keep reading as a person.

## 3. Current State & Blockers

`master` is at `a01962c`, 86 commits ahead of `origin/master` (`a9d1c41`); 85 of those predate this session. **Nothing was pushed** — every subagent run was checked with `git ls-remote` afterwards.

The gate passes: verified personally in a **fresh clone** with `core.autocrlf=true`, all 11 Go packages green, `gofmt -l cmd internal` silent, `go vet` clean, `uv run ultraloom check all` exit 0.

**The one thing this session got wrong and had to correct:** every "gate green" claim before the merge was true in the worktree but false for a fresh checkout. `core.autocrlf=true` rewrites the embedded templates and golden files to CRLF on checkout, which broke `internal/render`'s exact-string assertions *and* made `gofmt -l` list all 27 Go files. The worktree never re-checked those files out, so it never saw it. The whole-branch reviewer had noted it as an environment-dependent aside and it was left as one — too weak a reading. Fixed in `a01962c`; the lesson is that a gate claim is only worth what a fresh clone says.

**Open blockers:**

1. **The Stop hook's shell has no Go on PATH.** Since the Go arm joined the gate on master, every stop reports `gofmt`, `go vet` and `go test` as "file not found" while the code is green. A gate that always shows red gets ignored exactly like one that always shows green. Two paths were put to the user and **no answer was given**: resolve `go`/`gofmt` through the known install location (`C:\Program Files\Go\bin`) rather than the calling shell's PATH — recommended — or report the Go arm as *skipped* rather than failed when Go is unreachable.
2. **Every other existing checkout still holds CRLF files.** `.gitattributes` does not rewrite an existing tree. `.worktrees/installer-kern` and the two other worktrees each need a one-time refresh or re-clone.
3. **Three spec contradictions** were recorded rather than edited away, in `docs/.superpowers/sdd/2026-08-28-installer-kern/final-fix-report.md` (gitignored): the merge table says *report* where the error table demands exit 2; the same for a missing `fail_under`; and the exit-code table still promises "nothing written" and "all or nothing", which the code now honestly *reports* but does not *keep*. Reconciling them is a human decision.
4. **The spec's cross-language coverage merge step is absent.** A multi-language project gets one threshold and one lane with no merge. Needs its own plan.
5. **The new dependency** `golang.org/x/term` (plus `x/sys` indirect) went into a module that had one require. All 12 cross-compile targets still build without cgo, but the user may still want to veto it.

**Not reachable from any harness here:** the positive branch of `term.IsTerminal` needs a human running `ulinit` once in a real terminal; the two genuine-symlink tests skip on this Windows account for lack of privilege (a junction exercises the refusal instead).

## 4. Next Steps (Checklist)

- [ ] 1. Decide the Stop hook's Go lookup (resolve through the install path, or report *skipped* when Go is unreachable) — until then every stop shows a false red.
- [ ] 2. Decide the fate of `.worktrees/installer-kern`: `git merge --ff-only master` inside it to carry on, or retire it — and if retiring, move `progress.md` and `handover.md` out of its gitignored `.superpowers/` first, since nothing else records the session's rulings.
- [ ] 3. Refresh or re-clone the other checkouts so their working trees pick up LF.
- [ ] 4. Decide whether to push `master` to `origin` — 86 commits ahead, and the decision was deliberately left to a human.
- [ ] 5. Rule on the three recorded spec contradictions and on keeping `golang.org/x/term`.
- [ ] 6. Plan the cross-language coverage merge; then P2 (hook inventory — the `wiki` matcher and the timeout of 120 are currently reasoned inventions), P3 (OKF policy text as a fourth template), P5 (`ultraloom sync`, the first thing that reads `installed.toml`).
