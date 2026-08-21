"""The smallest real flow: check this project until everything is green.

Deliberately code-only — no AgentNode. It proves the runner, the journal and
the check chain work together before any model is involved. The flows that need
a model come with subproject 2.
"""

from dataclasses import dataclass
from pathlib import Path

from ultraloom.checks import run_check
from ultraloom.config import load_config
from ultraloom.graph import END, CodeNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    lint_ok: bool = False
    types_ok: bool = False
    report: str = ""


def _check(kind: str, data: Data) -> dict[str, object]:
    result = run_check(kind, load_config(Path.cwd()))
    return {f"{kind}_ok": result.ok, "report": data.report + f"{kind}={result.ok} "}


flow: Graph[Data] = Graph("smoke", start="lint")
flow.add(CodeNode("lint", lambda data: _check("lint", data)))
flow.add(CodeNode("types", lambda data: _check("types", data)))
flow.edge("lint", "types")
flow.edge("types", END)

initial = Data()
