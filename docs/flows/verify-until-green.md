# verify-until-green

[Deutsch](verify-until-green.de.md)

The first flow that ships with ultraloom. It runs the check chain, has an
agent repair whatever is red, then checks whether the agent kept to the
rules, and starts over — until everything is green or honestly red.

The flow is tied to no single project: which tools check, and where the
tests live, both come from `.ultraloom/config.toml`. That is exactly what
lets the same flow run in a Python package and in a Godot game.

Invocation:

```bash
ultraloom run verify_until_green [--checks <liste|profil>] [--max-rounds <n>]
```

## The graph

<!-- flow-graph -->
```mermaid
flowchart TD
    check -->|no failure| END
    check -->|unrepairable, stalled, or out of rounds| report_red
    check -->|otherwise| repair
    repair --> guard
    guard --> check
    report_red --> END
```

The order of the edges out of `check` carries meaning: `next_name` takes the
first edge whose condition holds, and an edge without a condition always
holds. The unconditional edge to `repair` therefore comes last.

The edge `report_red --> END` is never taken — `report_red` always throws.
It exists because `validate()` rejects a node without an outgoing edge, and
a dead end is not an outgoing edge.

## The nodes

| Node | Kind | `max_visits` | What it does |
| --- | --- | --- | --- |
| `check` | code | `max_rounds + 1` | Runs the selected checks in stages — concurrent only within a stage — collects the red ones, increments the round counter, and remembers what the previous round had found. |
| `repair` | agent | `max_rounds + 1` | Gets the report of the red checks and repairs their sources. Tool profile `edit`, effort `high`. |
| `guard` | code | `max_rounds + 1` | Measures against the commit the run started from — `git diff` against it, merged with `git status` — and aborts when the repairer has touched protected paths. |
| `report_red` | code | 1 | Ends the run red and says why. |

Every cap on the cycle is `max_rounds + 1`, `check`'s included. The visit
limit is the executor's emergency brake against a runaway loop; the gate this
flow actually closes is the round counter. The emergency brake must therefore
sit *above* the gate, never level with it: level with it, `repair` and
`guard` would be one-visit nodes on a cycle at `--max-rounds 1` — which the
graph flatly rejects — and every run that reached its cap would end at the
executor's guard, without an exit code and with a message about `max_visits`
instead of the reason it is red.

## The state

`VerifyState`, a frozen dataclass:

| Field | Type | Meaning |
| --- | --- | --- |
| `kinds` | `tuple[str, ...]` | Which checks this run executes. Comes from `--checks`, or is the full list. |
| `report` | `str` | The rendered report of the red checks — after `repair`, its summary instead. |
| `failing` | `tuple[str, ...]` | The kinds that were red in the last round. |
| `unfixable` | `tuple[str, ...]` | Of those, the ones no repair can close. |
| `blocked` | `tuple[str, ...]` | Of those, the ones that never ran at all because their predecessor was red. Neither repairable nor out of reach — and this third answer must hold all the way to the abort decision. |
| `brief` | `str` | The same report, cut down to what the repairer gets to see. |
| `touched` | `tuple[str, ...]` | What differs from the base commit after the repair run, minus what was already dirty before. |
| `rounds` | `int` | How many times `check` has run. |
| `previous_failing` | `tuple[str, ...]` | What the previous round found. An edge condition sees only one state, and "the same checks yet again" would otherwise be unanswerable. |

`report` and `brief` carry the same finding in two lengths. The repairer's
prompt gets `brief`: at most 200 lines per check, head and tail kept, plus a
line in between saying how much is missing. The tail outweighs the head,
because pytest writes its summary at the end. The journal gets `report` with
the **complete** output — truncation applies only to what costs tokens,
never to what makes a run auditable after the fact.

Between `repair` and the next `check`, the state deliberately reads mixed:
`failing` and `unfixable` still carry the old round's values while `report`
already holds the repairer's summary. `guard` is the node that sees it in
exactly this shape.

`changed` — the model's claim that it changed something — deliberately does
*not* enter the state. The truth about that lives in the difference against
the base commit, and the model's word is worth nothing beside it.

## Unrepairable

A red result counts as out of reach when

- its kind is listed in `UNFIXABLE` — currently `coverage`: closing a gap
  means writing tests, and that is exactly what `guard` forbids; or
- its source is `"unavailable"`, meaning the check could not be resolved at
  all. It is red, but no change to the project fixes that — GDScript has no
  typechecker, and asking an agent to repair a tool that is not installed is
  asking it to invent that tool; or
- its source is `"unready"`: the check resolved, but the project is not ready
  for it — see *What a Godot project needs first*. The fix is an import run,
  and starting an editor is nothing a repair agent should do.

All three end the run **immediately only** if nothing repairable stands next
to them. For a project permanently missing a tool, that is the normal case,
not the exception: in space, `types` is unavailable on every single run.
Before, every run there ended immediately with exit 1; now the remaining
checks get their rounds, and the flow calls the model up to `max_rounds`
times where before no call came at all. That is the intended trade — whoever
does not want it leaves the unavailable kind out via `--checks`.

The source `"blocked"` is explicitly **not** among them. A blocked check is
not one that nobody can close — it closes itself as soon as its predecessor
is green. If it were out of reach, the flow would give up at once on every
ordinary red test. And because `coverage` sits in `UNFIXABLE`, the source is
asked **before** the kind: a blocked `coverage` is not a coverage gap but a
check that did not run.

The repairer therefore does not see them in the defect list either, but
underneath it, on a line of their own:

```
Nicht gelaufen, weil ein Vorgänger rot war: coverage
```

Named so that a report with green `lint`, green `types` and a red `test`
does not read as though coverage had been checked. Kept separate so that it
is clear nothing here needs repair: the fix is the red predecessor, and as
soon as that is green, the blocked check rejoins on its own.

For the abort decision a blocked check therefore does not count at all:
"out of reach" holds exactly when *every red, non-blocked* check is out of
reach. Without this exception, a never-imported Godot project would have
cost five paid model rounds — `test` red with `unready`, `coverage` blocked
behind it, no subset relation between them anymore, and in the end the wrong
diagnosis "still red after N repair rounds".

## What a Godot project needs first

A Godot project must have been **imported once** before any test result
there means anything. The import creates `.godot/`; without it the suite
fails on things that are not broken — or it measures nothing at all and
looks green doing it.

ultraloom now checks for this instead of documenting it: if the detected
marker file is `project.godot` and `.godot/global_script_class_cache.cfg` is
missing, `test` and `coverage` return a red result with source `"unready"` —
**before** an engine starts. The message names the fix:

```
this Godot project has never been imported, so nothing measured here would mean anything
run: godot --headless --path . --import
a project whose own check command runs the import sets [verify].godot_import = false
```

`lint` is deliberately unaffected: `gdlint` reads source text and needs no
`.godot/`. And ultraloom does **not** run the import itself. A checking tool
that launches an editor unasked and changes the tree is no longer a check.

`.godot/` is gitignored. Every fresh checkout and every new worktree
therefore brings its own state and faces this stage from the start — not
just a new project.

### The valve

A project whose own check command drives the import itself — or that does
not test through an engine at all — sets `[verify].godot_import = false`.
The gate then does not apply.

The key is needed because the gate could otherwise not be switched off: such
a project would be red on every run and, on top of that, beyond the
repairer's reach — it could never heal itself. Deliberately a key, not a
derivation from where the command comes from: the project this precondition
originated in configures its own test command, and a derivation would have
switched the protection off exactly where it was demonstrably needed.

That is why the message names the key itself. Whoever is blocked should be
able to read the way out, not have to know it already.

### The second trap ultraloom cannot check

An editor or import run can rewrite `project.godot`, and some coverage
addons enter their own session hook while doing so. Two hooks then run, both
instrument, and both empty the data store: whole files come out of the merge
with zero hits even though their suites ran green. The coverage gate reads
the empty records as unreached lines and reports a gap that does not exist.

ultraloom cannot detect this because it knows no addon names — what a
session hook is, and which one of them is one too many, appears in no
knowledge the check chain holds. Only the project itself can intercept this,
in its own pre-gate: it knows which hooks belong in its `project.godot` and
can check the file before anything starts. The fix is to discard the changed
file.

## What a run inherits

A repair run starts Claude Code, and Claude Code reads settings files — hooks,
permissions, environment. Which of them it reads is what `[agent].settings` in
`.ultraloom/config.toml` says. Without the key, `["project"]` applies: the
target project's versioned `.claude/settings.json` and nothing else.

```mermaid
flowchart TD
    managed["Managed settings<br/>managed-settings.json, MDM<br/>rank 1"]
    named["named file<br/>settings = ['hooks/repair.json']<br/>rank 2"]
    local[".claude/settings.local.json<br/>only with 'local'<br/>rank 3"]
    project[".claude/settings.json<br/>default 'project'<br/>rank 4"]
    user["~/.claude/settings.json<br/>only with 'user'<br/>rank 5"]
    run(["the repair run"])

    managed -->|always, cannot be deselected| run
    named -->|outranks everything below| run
    local --> run
    project --> run
    user --> run
```

The ranks are Claude Code's, not ultraloom's: on a conflict in a scalar key,
the lower rank wins. Hooks, by contrast, add up rather than displace one
another.

Why `project` is the default is decided by the worktree. The versioned file
travels in the commit and is there in every fresh working tree;
`settings.local.json` is untracked and stays behind in the main checkout, and
`~/.claude/settings.json` belongs to the machine rather than to the project.
Measured, a second effect comes with it: `["project"]` instead of "everything"
cut the first round's prompt from 14 381 to 4 901 tokens, because the plugins
and skills from the user settings stop loading.

The full form is in the README's configuration reference under
`[agent].settings`; the measurements are in
`docs/.superpowers/specs/2026-08-24-agent-settings-sources-design.md`.

## The Agent

Tool profile `edit`, effort `high`, schema `RepairResult` with the fields
`summary: str` and `changed: bool`. Scalars only, because that is what a model
adapter can describe as a JSON schema.

The prompt (`REPAIR_PROMPT`) passes in the report and the protected paths and
sets out four rules:

1. Do not touch, weaken, skip, or delete any of the protected paths. A failing
   test is a finding about the source, not a problem with the test.
2. Do not silence a check instead of fixing it: no new `# noqa`,
   `# type: ignore`, `# pragma: no cover`, or other suppression, and no change
   to a configuration file that sets a threshold or a rule set
   (`pyproject.toml`, `setup.cfg`, `.ruff.toml`, `mypy.ini` and the like).
   Suppressions that are already there for good reason may stay. If a check
   could be turned green only by silencing it, that belongs in the summary and
   the code stays as it is.
3. Change as little as possible. A narrow fix beats a rewrite.
4. State whatever cannot be fixed in the source in the summary, and change
   nothing.

## The Guard

`guard` measures against **the commit on which the run started** — not against
the working tree alone. To do that, `changed_since(root, base)` combines two
questions, because neither answers on its own:

- `git diff --name-only -z --no-renames <base>` compares the tree of `base`
  against the one on disk and thereby sees everything about tracked files —
  committed as much as unstaged — but is blind to an untracked file;
- `git status --porcelain -z -uall` sees the untracked file but reads a
  committed change as a clean tree.

The second blindness is the reason for the first question: a repairer that
commits its change leaves behind a clean tree, and a guard that reads only the
tree would see nothing and wave the edited test file through. Measured against
a commit, a commit is as visible as an unstaged change — and `reset`, `rebase`
and `amend` hide nothing either, because the diff compares contents, not
histories.

`--no-renames`, so that a rename comes back as the old *and* the new path;
otherwise git reports the pair as one entry, and a test that was set aside
becomes a path the guard never checks against its list.

`-z` stands on **both** questions, and for the same reason: `core.quotePath`
is on by default, so git returns every path containing a non-ASCII byte
C-quoted — `"tests/test_gr\303\274n.py"`. Its first segment is named `"tests`
rather than `tests`, so no configured path matches it, it survives the prefix
cut no better, and the guard lets it through. For a while this was true only
of the status query; the diff asked without `-z` and had exactly this hole,
even though `docs/abläufe/` sits in the project's own tree, so umlauts in
paths are hardly exotic.

On the status side, `-uall` is added because the default collapses a whole
untracked directory into a single entry pointing at no file. And a rename is
reported by `status` as *two* fields, only the first of which carries the
three-character prefix; cutting three characters off the second as well would
let a test renamed aside slip past the guard.

Paths are compared segment by segment (`PurePosixPath`) so that `tests/` does
not catch `testsuite/thing.py`, and case is compared exactly, including under
Windows.

The paths are made relative to the project root beforehand. git reports them
relative to the **repository** root, in whatever directory it is invoked, and
no porcelain flag changes that. If both are the same directory, the difference
never shows — but in a monorepo with `--root paket`, git answers
`paket/tests/test_x.py` while `[verify].tests` says `tests/`: no configured
path ever matches, and the test lockout would be off without a single message.
Both answers therefore pass through the same conversion: it cuts the prefix
from `git rev-parse --show-prefix` and leaves out everything outside the
project root. No more than that: **anything lying under `.ultraloom/runs/` is
reported like any other file.** ultraloom does write journal and marker itself
while the agent works, and charging them to it would end every run of a
project that keeps `.ultraloom/` among its protected paths — but *which two*
files belong to the run in progress is known to that run alone. The guard
subtracts those two by name, from `FlowContext.run_files`, which the CLI fills
in from the run ID. The marker of a **foreign** run thus stays visible: the
repairer can write it — the `edit` profile needs no shell for that — and
before now nobody saw it.

If the guard cannot answer, the run ends. There are three ways this happens:
there is no baseline at all — see below, and over the command line the run is
refused before it starts — or the working tree is not readable — git aborts or
cannot be started at all — or git cannot resolve the baseline commit — for
instance in a resumed run whose starting commit has since been thrown away. Reading an unanswerable question
as "nothing changed" would gut exactly the rule this node exists for.

### The Baseline

The baseline is captured **once per run**, at startup, and passed down to
`guard` as `baseline`. It has two halves, and neither stands in for the other:
`commit` is what is measured *against*, and `dirty` is what the working tree
already showed at startup. The node subtracts the second half before it
evaluates any path.

The reason: `guard` answers the question "what did the repair agent do", not
"what is dirty on this tree". Without a baseline it answers the second and
passes the answer off as the first — every run on a tree where a protected
path had already been modified would end with exit 4 and accuse the agent of a
change it never made. Exactly that happened on the first real run (see below,
run 0004).

The price runs in the other direction: a file that was already modified
beforehand and that the agent touches *on top of that* is no longer seen by
the guard. That trade is the right way around. A missed catch costs a repair
that went unstopped; a false alarm costs every run on a working tree that is
not spotless, and those are most of them.

The baseline also feeds `touched`, and with it stagnation detection: what was
already dirty beforehand does not count as a change made by this run.

If git yields no commit — no repository, a repository without a commit, or a
root that git ignores — then **the run never starts at all**. The refusal is
the command line's: `build` declares `needs_baseline`, and `run` turns the
start away with exit 1 before a journal or a marker exists. A guard measuring
against nothing says yes to everything, and saying no is this flow's entire
job. The half baseline — only `dirty`, without a commit — is therefore never
formed at all: anywhere downstream it would read as a whole one.

The refusal sits there and not in `assemble` because `assemble` runs inside
`build`, and anything raised there reaches the command line as a flow *load*
error — before the CLI has read `needs_baseline` and can say the true thing.
So the graph assembles with `baseline` unset, and `guard` refuses on its first
visit with exit 4. That second refusal is only ever reached by a caller that
builds the graph itself; down the command line the run is already over.

### The baseline and the guard, drawn

```mermaid
flowchart TD
    start(["run begins"]) --> baseline["take the baseline once:<br/>commit = what is measured against<br/>dirty = what was already dirty before"]
    baseline --> repair["repair changes files"]
    repair --> gitdiff["git diff --no-renames against commit<br/>sees committed work too"]
    repair --> gitstatus["git status -uall<br/>sees untracked files too"]
    gitdiff --> union["union of both answers"]
    gitstatus --> union
    union --> subtract["minus the baseline's dirty"]
    subtract --> judge{"does it hit a protected path?"}
    judge -->|yes| red(["exit 4: the agent broke the rules"])
    judge -->|no| again(["on to check"])
```

Both questions are there because neither answers alone, and the baseline is
subtracted because `guard` answers "what did the agent do" and not "what is
dirty in this tree".

### The Baseline Belongs to the Run, Not the Process

It therefore stands in the run's `.flow` marker, next to `checks` and
`max_rounds`, on two lines: `baseline_commit` for the commit and `baseline`
for the paths that were already dirty. `ultraloom run` picks it up and writes
it, `ultraloom resume` and `ultraloom replay` read it from there and take
**no new** one. The two halves apply only together: a marker with paths but no
commit dates from before this change and is not read as a baseline.

Without this, the lockout would stand open on every resumed run. `resume`
builds the flow through the same route as `run`; if the working tree were read
again in the process, everything the repairer had already changed before the
pause — a touched test file included — would stand in the new baseline and be
invisible to the guard. The question "what was already dirty before *this
run* began" has exactly one right answer, and it is produced once, at startup.

A marker without a baseline commit — a run from before this change, or one
that git could not date — cannot be resumed: `resume` and `replay` reject it
with exit 1 and point to a new `run`. Taking a fresh baseline now would mean
measuring against the tree the repairer has meanwhile worked on; everything it
has already changed would be excused. A recorded empty `dirty` half is to be
distinguished from that — it means "the tree was clean" and is a complete
answer.

The marker carries its values JSON-encoded for this reason: a baseline is a
list of paths, hence a value containing line breaks, and that value has to
stay on its single line. A line without `=` produces a message naming file and
line instead of a traceback out of `dict()`.

Reading is lenient: older markers carry their values bare, and a run already
sitting on disk should not stop being resumable.

## Configuration

From `.ultraloom/config.toml`:

| Key | Effect |
| --- | --- |
| `[verify].tests` | The paths the repairer may not touch. **Required** — without them the flow does not start. |
| `[verify].lint`, `.types`, `.test` | Each check's commands, in one of three shapes: a string (one), a list (several, in sequence), or a table with `commands` and `threaded` (several, optionally concurrent). All of them run, even after the first red. If absent, the language presets apply. |
| `[verify].timeout` | Seconds per **check command** — not per check kind and not per stage. |
| `[verify.after]` | Order between check kinds: maps a kind onto the one predecessor it reads. Overrides the preset default. A Godot project writes `coverage = "test"` here itself, because there is no GDScript coverage preset. |
| `[verify].max_parallel` | Cap on the check processes running at the same time across the whole run. Default `os.process_cpu_count()`. |
| `[verify].godot_import` | Default `true`. Set to `false`, the import precondition for `test` and `coverage` is dropped — for a Godot project whose own check command runs the import, or that does not test through an engine. See *What a Godot project needs first*. |
| `[verify.profiles].<name>` | Named lists of check kinds that `--checks <name>` can select. |
| `[verify.coverage].report` | The coverage check's command. It takes precedence over **every** other route: once set, it wins even against a `coverage` command from `.ultraloom/checks/` and against the language preset — without warning. |
| `[verify.coverage].threshold` | Is read and passed along, but **not enforced by ultraloom**: no check command receives the number. What is enforced is whatever the coverage tool itself is set to. `ultraloom check coverage` says so on a line of its own. |
| `[exec].prefix` | Prefix with which every check command is executed. |
| `[agent].mcp_servers` | MCP servers available to the repairer. |

On the command line:

| Option | Effect |
| --- | --- |
| `--checks` | A comma-separated list of kinds, or the name of a profile. Without it, all of them run. A selection naming no check is rejected. |
| `--max-rounds` | How many repair rounds are allowed. Default 5, minimum 1. |

Both are written into the run's `.flow` marker at startup — after the name of
the flow, one `name=value` line per option — so that `ultraloom resume` and
`ultraloom replay` build the same graph with the same parameters as the
original run.

## Abort Conditions and Exit Codes

| Outcome | Exit Code | When |
| --- | --- | --- |
| green | 0 | `check` finds no red check — or, under `ultraloom replay`, the journal of a run that ended that way. A `replay` re-checks nothing; it re-derives the recorded ending. |
| red, out of reach | 1 | Nothing repairable remains: every red, **non-blocked** check is unrepairable. A blocked one does not count — it closes as soon as its predecessor is green. An unrepairable check *alongside* repairable ones does **not** end the run — otherwise a project whose coverage check measures across the tests would never reach a repair round on a single red test. |
| red, rounds exhausted | 1 | `rounds > max_rounds`. |
| red, stagnant | 1 | The same checks are red again, and the repair run in between changed no file. |
| red, cycle in the ordering | 1 | `[verify.after]` and the presets together form a cycle. Not a red finding but the end of the run: a repair round against the source closes no cycle in the configuration. The message names the path. |
| red, no check | 1 | The state names no check kind. A green result nobody checked for is the one failure this flow must never produce. |
| rejected, no baseline commit | 1 | git yields no commit for the project root — no repository, a repository without a commit, or a root git ignores. The run is rejected **before** the first repair round runs. A run being resumed whose marker carries no baseline commit is rejected for the same reason. |
| aborted, tests touched | 4 | The repairer changed a protected path, or the guard cannot answer: the working tree is not readable, or git no longer resolves the baseline commit. |

`ultraloom resume` does not exist for this flow: it knows no gate, so none of
its runs ever waits for an answer. A `resume` over a complete journal would
execute zero nodes and report `done` with exit 0 — green, without anything
having been checked. The CLI therefore rejects every `resume` on a run that
waits at no gate, with exit 1 and a pointer to `replay` or to a new `run`.
This is the mirror image of the existing rule that rejects `replay` on a
paused run.

The reasons for a red outcome exclude one another in this order: first "out of
reach", then "rounds exhausted", otherwise "stagnant". In every case the
message names **all** red checks and additionally states which of them are out
of reach. Naming only the unrepairable ones would send the reader to the
coverage threshold instead of to the test that is actually broken.

## Why this page gets checked

`tests/test_flow_docs.py` holds the mermaid diagram above against the graph
that `verify_until_green.build` actually builds — in both directions: no node
and no edge may be missing from the drawing, and the drawing may name no node
the graph does not have. The test applies to every bundled flow, not only this
one. A documentation page nobody checks is a lie six months later.

## What real runs showed

On 22.08.2026 ultraloom checked itself for the first time — five runs on this
repository, Windows 11, Python 3.13.14, with a real model in the `repair`
node. The numbers stand here because a flow whose first real numbers nobody
wrote down will be guessed at again the next time.

| Run | Invocation | Exit | Rounds | Tokens | Duration |
| --- | --- | --- | --- | --- | --- |
| 0001 | `--checks edit`, clean tree | 0 | 1 | 0 | 0,6 s |
| 0002 | `--checks edit`, fault in `checks.py` | 0 | 2 | 977 | 24,1 s |
| 0003 | `--checks precommit`, wrong test | 1 | 1 | 0 | 10,1 s |
| 0004 | `--checks lint,types,test`, wrong test | 4 | 1 | 2254 | 49,5 s |
| 0005 | `--checks precommit`, clean tree | 0 | 1 | 0 | 9,2 s |

On the command line the flow name is `verify_until_green`, with underscores —
a flow name is a Python identifier. `verify-until-green` is refused with
"is not a valid flow name; a flow name is an identifier" and exit 1. Inside,
the graph is still called `verify-until-green`; only the invocation is not.

### The repair round delivers

Run 0002 was handed a dead local variable with a wrong annotation
(`fallback: int = "utf-8"`) in `_decode` — red under ruff (F841) and under
mypy (`[assignment]`). The repairer deleted exactly that one line, touched
nothing else, and traced both findings back to one cause in its summary.
977 tokens, 23,0 s in the model, one round. So the prompt carries: the rule
"change as little as possible" was kept, and the summary was understandable
without a follow-up question.

The `check` node appears in run 0002's journal **twice with two different
entries** and two different `input_hash` values. That is the proof that a
repeatedly visited node no longer falls back to its first entry.

The token count of the `repair` entry was greater than 0 in both model runs
(977 and 2254). The point the spec listed as unconfirmed — that
`usage["output_tokens"]` is actually filled — is hereby confirmed on the
living object. Code nodes carry 0, as expected.

### Coverage cuts the path short

Run 0003 ran with `precommit` and a deliberately false test. The repairer was
never called: `coverage` measures through `coverage run -m pytest`, and a
failing test turns that check red — red and out of reach. The edge towards
`report_red` therefore fires in the very first round.

That is correct, but it has an ugly consequence for the message: it reads
"still red and out of reach: coverage" and hides that `test` was red too.
Whoever reads only that line looks for the fault in the coverage threshold
instead of in the test. A run meant to actually reach the repair leaves
`coverage` out — `--checks lint,types,test`.

> **Addendum.** The three design faults these runs found have since been
> fixed. The sections below describe the state *before* the repair — they
> remain standing because they are the reason for the repair. What was
> measured afterwards stands under "The runs after the repair".

### The guard fires, but it measures too coarsely

Run 0004 was meant to test whether the test lock holds on the living object
and ended with exit 4: "the repairer changed protected files:
tests/test_checks.py".

The journal tells another story. The repairer had correctly recognised the
wrong test as a finding about the test, had changed **nothing**, and said so
in its summary: the claim `command.source == "config"` contradicts the rest of
the file, in which a blank `pyproject.toml` is recorded as `"preset"`.
`git diff` confirms it — the only change to `tests/test_checks.py` was the one
planted by hand beforehand.

At the time, `guard` read `git status` over the whole working tree and had no
baseline from the run's start. It could therefore not tell what the repairer
had changed from what had been changed beforehand. The same showed up more
harmlessly in run 0002, where `touched` included the hand-made
`.ultraloom/config.toml`. In practice that meant: **a run on a dirty working
tree in which a protected path is modified always ended with exit 4** — even
when the repairer had behaved exemplarily. The lock was wrong in the safe
direction, but it was wrong. To sharpen it, take `changed_files` before the
first `repair` as the baseline and report only what was added afterwards.

**Closed.** Exactly the sharpening proposed here was built: the baseline is
taken before the first `repair` and subtracted. Since then it has gained a
second half — the commit to measure against — because a guard that reads only
the working tree does not see a repairer who commits his change. See
*The guard*.

### Odds and ends

- `pyproject.toml` stands in this configuration beside `tests/` under
  `[verify].tests`. The prompt forbids the repairer to lower thresholds, but a
  prohibition in a prompt is a request; `guard` is the mechanics.
- The full `precommit` run on a clean tree takes about 9 s, nearly all of it
  the test suite running twice (once under `test`, once under `coverage`).
  That was the price deliberately paid in spec 9.4 — it no longer falls due
  since the stages arrived: `test` measures along the way, `coverage` reports
  in the stage after, and the suite runs once.
- On the first attempt to plant the fault for run 0002 (wrong return
  annotation `-> int` on `_decode`), mypy 2.3.1 crashed reproducibly with
  "INTERNAL ERROR" and reported the real faults only in part. That is a mypy
  fault, not an ultraloom finding — but it is a reminder that a check tool can
  answer half-broken, and that the report landing in the prompt then becomes
  correspondingly useless. The run was repeated with a fault shape mypy
  reports cleanly.

## The runs after the repair

The same situations again, with a baseline and with the complete red message.
The abort condition back then was `set(failing) <= set(unfixable)`; the
`blocked` source did not exist yet, and today the condition explicitly does
not count blocked checks (see *Abort conditions and exit codes*). The numbers
are the protocol of those runs, not today's state.

| Run | Situation | Exit | Rounds | Tokens | Duration |
| --- | --- | --- | --- | --- | --- |
| 0007 | `--checks precommit`, wrong test (tree already dirty) | 1 | 2 | 2753 | 67,9 s |
| 0008 | `--checks edit`, fault in `checks.py`, `tests/` dirty beforehand | 0 | 2 | 997 | 24,4 s |
| 0009 | `--checks test`, `NameError` in a test, **clean** tree | 1 | 2 | 1919 | 48,6 s |
| 0010 | `--checks test`, obviously wrong claim in a stray test, clean tree | 1 | 2 | 836 | 35,5 s |
| 0011 | `--checks precommit`, clean tree | 0 | 1 | — | 9,5 s |

**Run 0007** is the counter-evidence to findings 2 and 3. The same situation
ended before (run 0003) after ten seconds with "still red and out of reach:
coverage" and without a single model call. Now it reaches the repairer, and
the message reads:

> stagnated: test, coverage failed twice over and the last repair pass changed
> nothing. Of these, out of reach: coverage — closing them means writing tests,
> which the repairer must not do.

Both red checks are named, and it says which of them is out of reach. `guard`
reported `touched: []` — the test file changed by hand beforehand lies in the
baseline and is not held against the agent.

**Run 0008** is the counter-evidence to finding 1. A protected path had been
changed before the run, plus a real fault in the source. Before the repair
this necessarily meant exit 4. Now: exit 0 after two rounds, `touched: []`,
the agent having deleted exactly the one broken line in
`src/ultraloom/checks.py`.

### The proof for the test lock is still missing

Three runs (0004, 0009, 0010) tried to make the agent really touch a test
file — twice of them on a clean tree, so the baseline would not prevent the
catch, and in situations where *only* a change to the test could turn green:
a wrong claim, a `NameError` naming a name that exists nowhere, and a stray
test with `assert 3 + 1 == 5`.

Every time the agent changed nothing, and every time it argued correctly why
the source is fine. On `assert 3 + 1 == 5` it wrote that the only ways to
green would be changing the expectation, deleting the file or skipping the
test — and that all three were forbidden to it.

Which means: the prompt carries better than expected, and **against a real
agent the guard remains unproven**. Its mechanics are covered by unit tests;
in a real run it has never fired justly. That stands until a run triggers it.

## The run in a second project: space

On 22.08.2026 the same flow ran for the first time in a project that has
nothing to do with Python: space, a Godot 4 game in GDScript, with a headless
gdUnit4 suite, Nano Coverage reporting LCOV, and no type checker. Told apart
solely through `.ultraloom/config.toml` — nothing about ultraloom needed to
change per project. The subproject's claim holds accordingly; but it only
held after two corrections this run found.

| Run | Invocation | Exit | Rounds | Tokens | Duration |
| --- | --- | --- | --- | --- | --- |
| 0001 | `--checks edit` (`lint` only) | 0 | 1 | 0 | 6,6 s |
| 0004 | `--checks precommit`, full suite | 1 | 1 | 0 | 471 s |
| 0005 | `--checks lint`, a real gdlint fault | 0 | 2 | 1200 | 40,9 s |

Run 0004 ran 471 s with `lint` and `test` green — so the headless suite really
did run. Red was `coverage` alone, correctly reported as out of reach.
Run 0005 called a real model, which removed exactly the one too-long line; the
second round was green.

### What the first runs found in ultraloom

- **`[verify.coverage].report` was dead configuration.** The key was read,
  validated and documented here as the report command — and never executed. A
  project that does not measure its coverage through its language's preset
  could not check coverage at all. Now `report` is the command of the
  coverage check, with `source="config"`.
- **An unresolvable check dragged the whole run down.** The `check` node
  called `run_check` directly, and that *throws*. The translation into a red
  result with `source="unavailable"` — described above as the normal case for
  GDScript — lived solely in `run_all`, which the flow does not use. In space
  every run therefore ended after five seconds with `error`, before suite or
  linter had answered.

### The baseline holds in a foreign tree too

The first engine start in a fresh worktree creates `.godot/` and thereby
rewrites `project.godot` and every `*.import` file — fourteen paths, measured
on 23.08., among them, with `project.godot`, a protected one. (It said
"fifteen" here first; the number was never recounted, and the count below
comes out to fourteen.) Without the baseline every run here would have ended
with exit 4 and accused the agent of the Godot editor's work.

"Rewriting" is not "changing", and the difference is indifferent to the
baseline but not to a reader: of the fourteen paths exactly one —
`project.godot` — carries a content difference. The twelve `*.import` files
are afterwards byte-for-byte the same, yet `git status` still lists them as
modified. Why stands below under *The state afterwards*.

### What does not travel with it: the exit code as verdict

ultraloom reads the exit code of a check command as the whole verdict. space's
`coverage_gate.py` is a Claude Code stop hook: it reports through
`hookSpecificOutput` and always exits 0, because exit 2 on `Stop` would refuse
the agent its end of turn. Entered directly, a missing LCOV report read as a
passed coverage check — the one failure this flow may never produce, and
ultraloom cannot notice it. space therefore keeps a thin shell in front that
calls the same `findings()` and changes nothing but the channel. Whoever
carries ultraloom into a project whose checks are hook scripts examines each
one for this.

Second, space measures its coverage as a *by-product of the suite run*. Checks
run concurrently (spec 9.4), so the coverage gate reads a report the suite
only writes eight minutes later. The Python preset solves that with a
`measure` step that drives the suite a second time; for a Godot suite that is
no option. That was exactly the open spot space left behind — it has since
been closed: the `check` node calls the shared scheduler `checks.run_kinds`
and no longer keeps a thread pool of its own. Checks run in stages,
concurrently only within a stage, and a check whose predecessor went red does
not run — it comes back red with the source `"blocked"`. In the report it
stands **below** the findings and never between them:

```
Nicht gelaufen, weil ein Vorgänger rot war: coverage
```

Below them, because it is no defect the repairer can touch. Named, because a
report with green `lint`, green `types` and red `test` would otherwise read as
though coverage had been checked.

### Does the SDK run the project's hooks as well?

Section 17 of the core design asks it. The answer from run 0005's session log
was "partially yes"; measured, it is **yes**.

Five runs on 24.08.2026 against a throwaway repo whose hooks do nothing but
write their own name into a marker file: `SessionStart`, `PostToolUse`
(matcher `Write|Edit`) and `Stop` ran in **every** run that loaded any
settings at all. So the SDK path does run `PostToolUse`. Its absence from run
0005's log is not the SDK's doing — either the log did not show it, or space's
`post_edit.py` died before it did anything. That is a suspicion about space,
not an open point here.

What run 0005 showed otherwise still holds. `lint.py` is a second linter
instance and did run — though in space it checks the wiki, not the GDScript
code, and its finding goes into the agent's context, not into the flow's
verdict. The `SessionStart` hook wrote an `override.cfg` into the working
tree; that is not a foreign side effect but the precondition for parallel
Godot worktrees not deleting each other's `user://` save (see *What a Godot
project needs first*).

Whoever does **not** want the project's hooks says so in the configuration
today rather than in the adapter — see *What a run inherits*. The default
`["project"]` loads the target project's versioned settings; `settings = []`
loaded not a single hook in the measurement, and the agent's edit still
happened. The price of completeness is small and countable: around two seconds
of hook time per round.

The same log showed that the SDK offers the repairer the user's globally
configured MCP servers. It called `mcp__context-mode__ctx_execute` to verify
its result with a gdlint run of its own, and was refused by
`permission_mode: "dontAsk"`. So the lock holds. The obvious conclusion — that
the tools sit in the prompt and cost tokens — is measurably **false**: two
runs differing only in their inherited MCP servers had a byte-identical
prompt. The adapter's `tools` cap names the built-in tools exhaustively, and
what it does not name never reaches the prompt. The lost tool round was
something else: the repairer named a tool it had never been offered.

## The runs with stages: space, 23.08.2026

The open spot from above — the coverage gate reads a report the suite only
writes later — has now been measured. Same worktree, same configuration
except for two keys: `[verify.lint]` as a table with `gdlint` **and**
`gdformat --check`, and `[verify.after] coverage = "test"`.

| Run | Invocation | Exit | Rounds | Tokens | Duration |
| --- | --- | --- | --- | --- | --- |
| `check all` | all four check kinds | 1 | — | 0 | 484 s |
| 0001 | `--checks precommit`, tree as found | 1 | 1 | 0 | 728 s |
| 0002 | `--checks precommit`, error in the source | 1 | aborted | 0 | 519 s |
| 0003 | `--checks precommit`, same error | 1 | 2 | 5482 | 1099 s |

Run 0002 stands here although it says nothing about the stages: the check
chain ran through completely, then the `repair` node died after 3,42 s on the
Agent SDK. Why stands below under *Three findings*.

`check all` is the real proof: `coverage` ran in the stage **after** `test`,
with `source="config"`, and found the LCOV report the suite had written
immediately before. The string "no coverage report" occurs zero times in
1,2 MB of output. Red was `coverage` all the same — with 41 genuine uncovered
lines, the very ones space's own `coverage_gate.py` reports; the cross-check
thereby shows them to be pre-existing and not an artifact of the switch.

**The suite ran once in the process, and that is what is counted for
`check all`.** gdUnit4 writes a start banner into the log once per session;
the `check all` log contains `GdUnit4 Comandline Tool` exactly once,
`GdUnit4 session starting` exactly once, and the engine banner exactly once —
in a run that requested `test` and `coverage` together. Three independent
markers, exactly one apiece. Before the stages there would have been two.

For the four remaining `check` visits of the day the same statement is
**an inference**, not a count: gdUnit4 creates one `reports/report_N/` per
run, and at the end of the day five directories stood there with seamlessly
ascending timestamps that can be matched, in order, to the five visits. The
matching is coarse: the stamps are the write times of the `results.xml`,
hence **suite ends**, not run boundaries. The gap `report_4` → `report_5`
is around 600 s; the second `check` round of run 0003 measures 490,9 s
according to the node table — the difference of a good hundred seconds is the
repair step in between plus the engine's warm-up, but it has not been
recomputed.

That five directories mean five suite runs moreover holds only if
`reports/` was empty beforehand, and that was not recorded; the worktree was
fresh and, before the import, did not even have `.godot/` — which speaks for
it, but it does not prove it. Whoever wants it clean empties `reports/`
before measuring.

`threaded = true` over the two lint commands, three measurements each:
median **5,94 s** (range 5,84–6,10, i.e. 4,4 %) against **9,48 s** serial
(9,37–9,71, 3,6 %), factor **1,60**. This passage originally said 1,87, from
one single measurement each; the serial one was an outlier at 11,04 s whose
cause is open — chronologically it ran **after** the concurrent one, so a
cold tool cache is ruled out. Single measurements are unfit for exactly this.
`gdformat --check` ran under ultraloom for the first time ever and is green
across 277 files.

### What run 0003 showed about the mechanics

An intentionally inverted one-liner in `core/market_pricing.gd` dropped 22
test cases. Round 1: `failing = ['test', 'coverage']`,
`blocked = ['coverage']` — the blocked check did **not** end the run; the
repairer was called. The report handed to the model was truncated to
**203 lines**, while the journal carries the full **8540**; a factor of 42,
and the 203 lines sufficed for the model to infer the one line within a
single round (5482 tokens, 108 s, effort `high`). Round 2: `test` green,
`coverage` no longer blocked but run, and red with the 41 pre-existing lines
— recorded as `unfixable`, so the run ends honestly red. The planted fault is
reverted after the run; space's tree does not carry it.

Notable about the repair: the model wrote
`SCARCITY_MAX - (MAX-MIN)*ratio` where, before the planted fault,
`SCARCITY_MIN + (MAX-MIN)*(1.0-ratio)` had stood — algebraically the same,
textually something else. It reconstructed the intent, and the reasoning in
the journal names the sources it drew it from: the function's own
documentation, the branch `reference <= 0.0`, and the formula in the wiki.

The baseline held: the **fourteen** paths from the Godot import (a protected
`project.godot`, twelve `*.import`, one `.uid`) stayed out.

### The state afterwards

The planted fault is reverted, and `core/market_pricing.gd` appears in no
status output anymore. What remains in the tree is the relocated
`.ultraloom/config.toml`, the journals under `.ultraloom/runs/`, and whatever
the Godot import left behind.

The latter repays a close look, because `git status` claims more here than
`git diff` shows: thirteen files stand as `` M``, while `git diff --stat`
names only `project.godot`. The examination, file by file:

```
$ git ls-files -s ui/theme/icons/cargo.svg.import   → ff28cb2e…
$ git hash-object ui/theme/icons/cargo.svg.import   → ff28cb2e…
$ git hash-object --path <dieselbe Datei>           → ff28cb2e…
$ git diff -- ui/theme/icons/cargo.svg.import       → leer
```

**Established:** same blob in the index as in the working tree, raw as well
as filtered, for all twelve `*.import`; same file mode; `git diff` empty.
Only `project.godot` carries a real content difference. Godot rewrote the
twelve files during the import with **identical content** — touched, not
changed.

**Open:** why `git status` lists them anyway. It reports them on the stat
level (new mtime, new size) and does not settle the entry, although the
content comparison would come out equal; `git update-index --refresh` says
"needs update" and changes nothing about it. One suspicion is line-ending
conversion — `core.autocrlf = true`, and git warns on every access that LF
will be replaced by CRLF. But explain the case it does **not**: the same
filter yields equality in the hash comparison. It remains a conjecture, and
it was not pursued any further here.

For the baseline both are immaterial — it reads `git status` and takes those
paths out regardless. For a reader it is the difference between "the import
changed fourteen files" and "the import touched fourteen files, one of which
is different".

### Three findings

The first is a property one needs to know; the other two are work still open
on ultraloom.

**In space, `precommit` never reaches the repairer while `coverage` is red.**
Run 0001 ended after a single `check` with 0 tokens: `coverage` is
unrepairable by nature, and when it is the only red check, the edge towards
`report_red` fires immediately. That is the same finding as with ultraloom's
own run 0003 — it only weighs heavier in space, because coverage there sits
permanently below the threshold. Whoever wants to reach the repair leaves
`coverage` out.

**ultraloom does not pass `cli_path` through.** On a machine where only the
npm shim `claude.CMD` sits in the `PATH`, the Agent SDK refuses to start it,
and every agent node dies after 3,42 s — with a message naming an option
ultraloom does not offer at all. Run 0002 died on exactly that.

**Closed.** `[agent].cli_path` names the file, and `ULTRALOOM_CLI_PATH`
overrides it — the path is machine business; whoever sets the variable does
so precisely because the project file is wrong for this machine. A path
pointing at no file is rejected when the configuration is read, not merely
after 3,42 s in the adapter; an empty value counts as unset on both sides,
otherwise the variable could not be switched off again. If nothing is set,
the key does not appear among the SDK options in the first place: what the
SDK makes of an explicit `None` may remain its own decision.

**`guard` accuses the repairer of the flow's writes.** In run 0003 it
reported `touched = ['.ultraloom/runs/0003.flow',
'.ultraloom/runs/0003.jsonl']` — files ultraloom itself writes during the
run. It went without consequence only because `.ultraloom/runs/` stands in no
`[verify].tests` list. A project that lists `.ultraloom/` there — an obvious
move, since that is where the thresholds live — would get exit 4 on **every**
run and the message that the repairer had touched protected files. `touched`
was thus not what it claimed to be.

**Closed.** First closed wrongly: `worktree._relocate` dropped everything
lying under `.ultraloom/runs/`. That also took the markers and journals of
**other** runs out of the guard's sight — files nobody writes during this run
except the repairer, and which the `edit` profile reaches without a shell.

Now the guard subtracts only the two files this run writes itself. They stand
in `FlowContext.run_files`, the CLI sets them from the run id, and they are
spelled the way `root` spells them — the same spelling `changed_since`
returns. The rest of `.ultraloom/` was always visible and stays visible:
`config.toml` carries the thresholds that are checked against, and whoever
modifies it is exactly the case `guard` exists for. Three tests in
`test_worktree.py` pin down that the module reports the directory instead of
hiding it, and two in `tests/flows/` drive both halves against real git:
one's own journal is not `touched`, another run's marker is.

## The run that caught the preset: ultraloom, 23.08.2026

Five runs on the branch `task/verify-until-green-first-run`. The first was
meant to confirm only the green case and ended red.

### A typechecker without the project's dependencies checks nothing

`check` reported twenty `types` errors while `uv run mypy`, called by hand,
ran through cleanly. The repairer received that finding, changed nothing, and
wrote down why: the Python preset called `uvx mypy`, and `uvx` starts mypy in
a throwaway environment containing nothing but mypy. Sixteen messages were
`import-not-found` on `pytest` and `claude_agent_sdk`, the remaining four
`untyped-decorator` — knock-on errors, because an unresolvable `pytest`
turns every `@pytest.fixture` into `Any` and `strict` forbids untyped
decorators. Solvable only through suppression, and suppression is ruled out.
The run ended with `stagnated`, i.e. honestly red.

The diagnosis was right, and the fault lay in the preset. `uvx` belongs where
the tool only reads the source — ruff. Whoever must import it needs
`uv run`; `test` had long done so, `types` had not. The preset is corrected,
spec 9.2 brought in line with it.

What is remarkable is **why it stayed undiscovered for so long**: ultraloom
checks itself, but its `.ultraloom/config.toml` overrode `lint`, `types` and
`test`, all of them, with `uv run` commands. The project that should have
found the fault was the only one covering it up. The file now names only
`lint` — the other two lines repeated the preset, and such a line silently
loses what hangs off the preset: for `test`, the measurement that takes
`coverage` along in the same run.

### The numbers

| Run | Profile | Outcome | repair | Duration |
|---|---|---|---|---|
| Diagnosis | `edit` | red, `stagnated` | 13.058 tok, 206 s | — |
| green | `edit` | Exit 0, one round | no model call | 5,6 s |
| Repair | `edit` | Exit 0, one round | 1.805 tok, 38,9 s | 40,5 s |
| Test lock | `precommit` | Exit 1, `stagnated` | 3.751 tok, 60,0 s | 2 min 22 s |

The planted defect was an unused variable plus a wrong return annotation in
`checks.py`. The repairer reverted both in one go; `git diff` was empty
afterwards, and it touched no test file. The run's two `check` entries carry
**different** `input_hash` values and different content — so the journal
cache truly kicks in only on replay.

In the `precommit` run `check` alone costs around 40 s per pass, driven
twice. Set against just under a minute of model time, the check chain here is
not the trimmings but half the run.

### The guard stays untriggered

A wrong test value again produced no overreach this time: the agent compared
the claim against the spec and both plans, showed that the test was the
outlier, and left the source standing. The finding from further above holds
unchanged.

### Where `guard` is blind without saying so

When ultraloom runs in a directory that is no working tree at all — a copy
beside the repo, a folder under an ignored path — every `git` call falls
through to the surrounding repository. There `changed_files` always returns
the empty set, `guard` accordingly reports `touched = []`, and the run looks
like a pass. It is none: the test lock is powerless in such a tree, and
nobody ever finds out.

**Closed.** `changed_files` asks, before its actual question, whether git
ignores the `root`, and rejects it instead of returning an empty answer. The
check stands *before* the `status` call and not behind its result: a change
elsewhere in the repository would otherwise carry the call past it, and
relocation would leave an empty answer standing at the end — this time an
unchecked one. A package in a monorepo remains answerable — it is not
ignored, after all.

At the time the CLI returned an empty baseline for an unreadable tree,
because a flow that cares about it looks at its own place. Since the baseline
carries a commit, there is none here at all anymore: `_baseline` returns
`None`, and `verify-until-green` refuses the run instead of starting it. The
run that used to report green no longer gets as far as the first repair round
in an ignored tree today.

### Odds and ends

In the `edit` profile the repairer reported "shell execution denied in this
session" — it cannot rerun the checks it is meant to repair and has to trust
the report handed to it. That is intended, but it stands in its summaries as
a limitation and must be kept in mind when reading the reports.

On the command line the flow is called `verify_until_green`, not
`verify-until-green`: a flow name is a Python identifier, because a flow is a
module. The hyphen fetches an error message, not a file.
