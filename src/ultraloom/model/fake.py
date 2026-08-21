"""A model that answers from a queue, for tests."""

from __future__ import annotations

from collections.abc import Sequence

from ultraloom.model.port import ModelError, Reply, Request


class FakeModel:
    """Hands out prepared replies and records what it was asked.

    A queued ModelError is raised rather than returned, so error paths are as
    testable as happy ones.
    """

    def __init__(self, replies: Sequence[Reply | ModelError]) -> None:
        self._pending = list(replies)
        self._seen: list[Request] = []

    @property
    def seen(self) -> tuple[Request, ...]:
        """Every request this model was handed, in order."""
        return tuple(self._seen)

    def ask(self, request: Request) -> Reply:
        """Return the next prepared reply."""
        self._seen.append(request)
        if not self._pending:
            raise ModelError(f"no reply left for {request.prompt!r}")
        nxt = self._pending.pop(0)
        if isinstance(nxt, ModelError):
            raise nxt
        return nxt
