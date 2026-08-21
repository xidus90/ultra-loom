"""The model interface every AgentNode goes through.

Keeping the model behind a port is what makes the whole core testable without
the network — and it leaves the door open for a node to reach the model a
different way than its neighbours do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ModelError(RuntimeError):
    """Raised when a model cannot answer: unreachable, refused, schema broken."""


@dataclass(frozen=True, slots=True)
class Request:
    """One model call, fully described."""

    prompt: str
    tools: tuple[str, ...]
    effort: str
    schema: type


@dataclass(frozen=True, slots=True)
class Reply:
    """A schema-validated answer and what it cost."""

    value: object
    tokens: int


class Model(Protocol):
    """What the runner needs from a model."""

    def ask(self, request: Request) -> Reply:
        """Answer one request, or raise ModelError."""
        ...
