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
the one failure in this system that actually does damage.

In Python, `check coverage` measures before it reports: `coverage report` only
reads a file that some earlier run has to have written. That means the test
suite runs twice in `check all`, once under `test` and once under `coverage`.
The alternative would be to make the two checks depend on each other, and they
run at the same time precisely because they do not. A project that minds the
second run puts its own script at `.ultraloom/checks/coverage.py`.

A check is resolved in this order, and ultraloom never guesses beyond it:

1. `[verify].<kind>` in `.ultraloom/config.toml`
2. `.ultraloom/checks/<kind>.*` — a script you wrote. A `.py` file is run with
   ultraloom's own interpreter, anything else directly. With more than one
   match the first by name wins, so keep one script per check.
3. the preset for the language ultraloom detects from a marker file
   (`pyproject.toml`, `package.json`, `project.godot`)

A check that cannot be resolved is reported as a failure, never skipped.

## Configuration

`.ultraloom/config.toml`, all of it optional:

```toml
[verify]
lint = "ruff check ."
types = "mypy src"
test = "pytest -q"

[verify.coverage]
threshold = 100
report = "coverage.xml"

[exec]
# Put in front of every check command, for a project that builds in a container.
prefix = "docker compose exec -T web"

[agent]
# MCP servers an agent node with the "mcp" tool profile may reach.
mcp_servers = ["wiki"]
```

## The harness (optional)

    uv add "ultraloom[agent]"

Runs a flow as a graph: nodes are steps, edges are transitions with
conditions. It journals every step, stops at approval points, and resumes an
aborted run from where it stopped.

    ultraloom run <flow>       # start a flow; prints a run id
    ultraloom show <id>        # print that run's journal, one line per step
    ultraloom resume <id> --answer "yes"
    ultraloom replay <id>      # re-derive the run from its journal, no model call

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
flow.edge("write", END)

initial = Data()
```

`flow` must be a `Graph`; `initial` is the frozen dataclass the run starts
from. The module is executed on every load and is never registered in
`sys.modules`.

### The journal, and what a resume replays

A resume keys on a node's *input* — its name and the data it saw — not on its
code. Edit a node in the middle of a run and resume, and you get the old result
back from the journal. Start a fresh run when a node changes.

The same cache governs `run`: a `run` over a journal that already covers the
flow executes nothing and returns the recorded deltas.

That has one consequence worth knowing before you write a loop. `max_visits`
raises a node's ceiling so it may sit on a cycle, but every pass that leaves
the payload unchanged hits the same journal key and is served from the journal
rather than executed. A bounded cycle only does work if each pass advances the
payload; otherwise the node runs once and spins until the ceiling stops it.
ultraloom says so in the error when that happens.

### Exit codes

| code | meaning |
| ---- | ------- |
| 0 | the command succeeded; a flow run reached its end |
| 1 | a check failed, or the command could not be carried out |
| 2 | argparse rejected the command line (its own convention) |
| 3 | the flow paused at an approval point and is waiting for an answer |

## Licence

AGPL-3.0-or-later. See `LICENSE`.
