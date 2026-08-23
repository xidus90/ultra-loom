# ultraloom

A check chain that puts one interface in front of ruff, eslint, gdlint, mypy,
tsc, pytest, vitest and coverage — and an optional graph harness for agent
flows.

## The check chain

    uvx ultraloom check lint
    uvx ultraloom check types
    uvx ultraloom check test
    uvx ultraloom check coverage
    uvx ultraloom check all

No installation in your project, no LLM dependency, no API key. The tool for
each check comes from a language preset; the place it runs comes from your
project's `.ultraloom/config.toml`.

`--threshold` sets the number ultraloom *reports* beside the coverage check.
ultraloom does not enforce it — your coverage tool's own configuration decides
whether the run passes. A line reading "ok" for a threshold nobody checked is
the one failure in this system that actually does damage. Concretely, for
Python: `coverage report` takes its exit code from `fail_under` and from
nothing else, so without that key in the project's own configuration a run at
83% is green. The same holds for `[verify.coverage].report` — naming a report
command does not make anybody enforce a number.

In Python, `check coverage` measures before it reports: `coverage report` only
reads a file that some earlier run has to have written. Who does that measuring
follows from the set of checks you asked for, not from the table alone — see
*Order between checks* below. In `check all` the suite runs **once**: `test`
runs under `coverage run`, and `coverage report` reads what it wrote, in the
stage after it.

A check is resolved in this order, and ultraloom never guesses beyond it:

1. `[verify].<kind>` in `.ultraloom/config.toml`
2. `.ultraloom/checks/<kind>.*` — a script you wrote. A `.py` file is run with
   ultraloom's own interpreter, anything else directly. With more than one
   match the first by name wins, so keep one script per check.
3. the preset for the language ultraloom detects from a marker file
   (`pyproject.toml`, `package.json`, `project.godot`)

A check that cannot be resolved is reported as a failure, never skipped.

The presets ask their tools for their terse modes, because a check report is
read by a repairing agent that pays for every token of it on every round. One
consequence is worth knowing in advance: `mypy --no-error-summary` drops the
"Success: no issues found" line too, so a green `types` check writes nothing at
all. The verdict rides on the exit code, as it always has — but an empty report
is not a check that did not run. GDScript has no coverage preset for the same
family of reasons: the tools that measure it are an editor addon and a
project-owned script, neither of which is a command another project could run,
and inventing one would look like a check without being one. Such a project
names its own under `[verify.coverage]`.

## Configuration

`.ultraloom/config.toml`, all of it optional:

```toml
[verify]
lint = "ruff check ."                 # a string: one command, as before
types = ["mypy src", "pyright"]       # a list: several, one after the other
test = "pytest -q"
max_parallel = 4                      # default: os.process_cpu_count()

[verify.lint]                         # a table: several, with switches
commands = ["gdlint .", "gdformat --check ."]
threaded = true

[verify.after]                        # order between checks
coverage = "test"

[verify.coverage]
threshold = 100
report = "coverage.xml"

[exec]
# Put in front of every check command, for a project that builds in a container.
prefix = "docker compose exec -T web"

[agent]
# MCP servers an agent node with the "mcp" tool profile may reach.
mcp_servers = ["wiki"]
# Where the Claude CLI is, when the SDK's own search does not find it.
cli_path = "C:/Users/me/AppData/Local/Programs/claude/claude.exe"
```

`[agent].cli_path` is for the machine whose only Claude CLI is something the
SDK refuses to start -- an npm shim named `claude.CMD`, say. Without it every
agent node dies a few seconds in, on a message naming an option ultraloom did
not offer. `ULTRALOOM_CLI_PATH` says the same thing and **beats** the file:
whoever exports it does so because the project's file is wrong for this
machine, and the other way round the variable would be dead everywhere as soon
as one project wrote the key down. A blank value on either side counts as
unset, which is how a machine that exports the variable switches it off again.
A path that is not a file is refused when the configuration is read -- before
the first node, rather than once per agent call.

`lint`, `types` and `test` take three shapes, told apart by type: a string is
one command, a list is several, and a table is the full form with `commands`
(required, not empty) and `threaded` (default `false`). A string and a table
under the same name is something TOML cannot express, so the parser refuses it
before ultraloom sees it.

`coverage` takes **none** of the three, and says so in every shape: a string or
a list under `[verify]` is refused with "[coverage] must be a table" (the
message names the leaf, not the full heading),
and a `[verify.coverage]` carrying `commands` or `threaded` is refused by name
with a pointer at `report`. That is where the command belongs. What is *not*
caught is a typo inside `[verify.coverage]` — a key that is neither `report`
nor `threshold` is ignored without a word, so `reprot = "…"` leaves the check
on its script or its preset.

Every command of a kind runs, including the ones after the first red one: the
repairer is owed the whole list of findings, and half a list costs another paid
round through the model. `threaded = true` runs them at the same time, and is
therefore a pure speed switch — the verdict is the same either way. The timeout
applies per command, so a linter's deadline does not depend on how many
siblings it has. An empty `commands`, or a blank command in it, is an error:
what would run is the `[exec].prefix` alone, and a prefix that exits 0 reports
a check nobody configured as passed.

`max_parallel` caps the check *processes* running at once over the whole run —
stages, kinds and commands share one counter, and reader threads do not count
against it. Without that cap `threaded = true` is a foot-gun: four Godot
processes at once is not four times the speed.

### Order between checks

Checks run in **stages**: concurrently inside a stage, one stage after the
other. The edges come from the language preset; `[verify.after]` overrides
them and maps a kind onto the single kind it reads from.

| language | stage 0 | stage 1 |
| --- | --- | --- |
| Python | lint, types, test | coverage |
| Node | lint, types, test, coverage | — |
| GDScript | lint, test | (none) |

Node stays single-stage because `vitest run --coverage` measures and reports in
one run. The table shows what the *presets* answer for a run that asks for
every kind; a project that configures a kind itself gets its own command, and a
stage only exists for the kinds actually requested.

The GDScript row is short because two presets are missing, and neither is an
oversight in this table. There is no `types` preset — GDScript has no type
checker to name, so `check types` in a Godot project falls through to a red
"GDScript has no types tool — a known limitation, not a passed check" — unless
the project names a command of its own under `[verify].types` or puts a script
at `.ultraloom/checks/types.*`, both of which are found first. And
there is no `coverage` preset — the tools that measure GDScript coverage are an
editor addon and a project-owned script, neither of which is a command another
project could run. There is therefore no second stage at all until the project
makes one: a Godot project that measures coverage names its report command under
`[verify.coverage].report` **and** its order under `[verify.after]` —
`coverage = "test"` — itself. Both gaps are gaps in the presets, not in this
page.

A kind that was not requested drops out of the stages without holding the rest
up: `check coverage` on its own runs immediately rather than after an empty
stage 0. A cycle in the edges is refused with the path it found, not walked
into.

**Who measures, in one sentence:** if the check I wait for runs in this same
pass and can measure as a by-product, it measures — otherwise I measure myself.

| requested | `test` runs as | `coverage` runs as | suite runs |
| --- | --- | --- | --- |
| test + coverage | `coverage run -m pytest` | `coverage report`, the stage after | 1 |
| test only | `pytest` | — | 1, with no measuring overhead |
| coverage only | — | measure, then report | 1 |
| `check all` | `coverage run -m pytest` | `coverage report`, the stage after | 1 |

A project that configures `test` itself has no measuring variant ultraloom
knows about, so `coverage` falls back to measuring for itself. ultraloom does
not guess whether somebody else's test command measures.

### Why a check is red

Besides a tool that simply found something, a red result carries a source:

| source | meaning |
| --- | --- |
| `unavailable` | the check could not be resolved at all — no config, no script, no preset. Red, never skipped. |
| `unready` | it resolved, but the project is not ready for it (a Godot project that was never imported). |
| `blocked` | it did not run, because the check it waits for was red. |

`blocked` is red like the others and is not skipped — but it is not out of
reach either: it closes itself the moment its predecessor is green. It is
therefore not something a repairer should touch, and `verify-until-green`
leaves it out of the decision to give up.

### Before you configure a check

**A check command that comes from a hook script has to be looked at.** ultraloom
reads the exit code and nothing else. Hook scripts routinely report their
findings on stdout and exit 0 on purpose — a Claude Code `Stop` hook that
exited 2 would refuse the agent its end of turn. Entered directly as a check
command, such a script reads as a passed check whatever it found, and ultraloom
cannot tell. Put a thin shell in front of it that calls the same findings and
only changes the channel.

**A command that leaves a long-lived grandchild behind is red**, even when it
exited 0, and it costs five seconds on top. ultraloom collects a command's
output on reader threads; a daemon or server the command started keeps the pipe
open, the readers cannot be joined, and they are given up on after a grace
period. What came back is then a prefix — and a threshold or a failure count
may be in the part that did not. A check whose output nobody could read in full
is not a passed check. The report says so in its own words.

## The harness (optional)

    uv add "ultraloom[agent]"

Runs a flow as a graph: nodes are steps, edges are transitions with
conditions. It journals every step, stops at approval points, and resumes an
aborted run from where it stopped.

    ultraloom run <flow>       # start a flow; prints a run id
    ultraloom show <id>        # print that run's journal, one line per step
    ultraloom resume <id> --answer "yes"
    ultraloom replay <id>      # re-derive the run from its journal, no model call

### verify-until-green

The flow ultraloom ships with. It runs the checks, hands every red one to the
repairer, and runs them again — until everything is green, until nothing moves
any more, or until the round ceiling is reached.

    ultraloom run verify_until_green
    ultraloom run verify_until_green --checks lint,types
    ultraloom run verify_until_green --checks quick --max-rounds 5

Underscores on the command line: a flow name is a Python identifier, so
`ultraloom run verify-until-green` is refused with exit 1. The graph is still
called `verify-until-green` inside — only the invocation is not.

`--checks` takes a comma-separated list of check kinds, or the name of a
profile from `[verify.profiles]`. Left out, the flow runs every check.
`--max-rounds` caps the repair rounds; left out, the flow's own limit applies.
The flow itself checks both while it builds, and refuses to start with a
message naming what it expected — so a typo never turns into a long run.

The repairer may not touch the paths in `[verify].tests` — a check that goes
green because its test was edited is the one repair worth nothing. Coverage is
never repaired at all, for the same reason: closing a coverage gap means
writing tests.

```toml
[verify]
# Required by this flow: the paths the repairer must leave alone.
tests = ["tests"]
# Seconds a single check may take before it is cut off.
timeout = 600

[verify.profiles]
quick = ["lint", "types"]
full = ["lint", "types", "test", "coverage"]
```

Exit codes: `0` green, `1` still red after the last round, `3` waiting at an
approval point, `4` the run was stopped over the protected test paths — either
the repairer touched one, or the working tree could not be read to tell.

The flow is described at length — in German — in
`docs/abläufe/verify-until-green.md`.

### Writing a flow

A flow is a Python module at `.ultraloom/flows/<name>.py`. Its name must be a
plain identifier. The module defines two things at module level:

```python
from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("greet", start="write")
flow.add(CodeNode("write", lambda d: {"note": "hello"}))
flow.add(
    GateNode(
        "approve",
        question=lambda d: f"send {d.note!r}?",
        apply=lambda d, answer: {"note": answer},
    )
)
flow.edge("write", "approve")
# Every node needs a way out, including the last one: it leaves towards END.
flow.edge("approve", END)

initial = Data()
```

`flow` must be a `Graph`; `initial` is the frozen dataclass the run starts
from. The module is executed on every load and is never registered in
`sys.modules`.

### The journal, and what a resume replays

A `run` executes every node it reaches. The journal is read only while a walk
is *retracing* one: a `replay` retraces from the first entry to the last, a
`resume` retraces up to the point where the earlier run stopped and does real
work from there.

What is retraced is keyed on a node's *input* — its name and the data it saw —
not on its code. Edit a node in the middle of a run and replay, and you get the
old result back from the journal. Start a fresh run when a node changes.

So a loop does work even when it leaves its payload alone. `max_visits` raises
a node's ceiling so it may sit on a cycle, and every pass of that cycle really
executes — which is what a node that measures the outside world without
changing it needs.

### Exit codes

| code | meaning |
| ---- | ------- |
| 0 | the command succeeded; a flow run reached its end |
| 1 | a check failed, or the command could not be carried out |
| 2 | argparse rejected the command line (its own convention) |
| 3 | the flow paused at an approval point and is waiting for an answer |
| 4 | a flow stopped itself; verify-until-green uses it for the protected test paths |

## Licence

AGPL-3.0-or-later. See `LICENSE`.
