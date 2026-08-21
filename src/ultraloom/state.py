"""The immutable state that travels through a flow."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

type Delta = Mapping[str, object]


class NotADataclassError(TypeError):
    """Raised when a flow's payload is not a frozen dataclass."""


@dataclass(frozen=True, slots=True)
class State[T]:
    """A flow's payload plus how often each node has run.

    Nodes never write into a state; they return a delta and the runner builds
    the next state from it. Without that rule a resume could not reconstruct
    the state a node saw before it ran.
    """

    data: T
    visits: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # T cannot be bound to "is a frozen dataclass" in the type system, so
        # the guarantee `merged` relies on is checked once, here, at the door.
        # Frozen is not decoration: a payload a node could write into in place
        # would leave the journal's record of the input describing something
        # other than what the node saw, and a resume would replay a fiction.
        # `__dataclass_params__` is where the decorator records the frozen
        # flag, and its absence on the payload's *type* is exactly the "not a
        # dataclass instance at all" case — a class object passed instead of
        # an instance lands here too, since `type` carries no such attribute.
        # Neither fact has a public accessor.
        params = getattr(type(self.data), "__dataclass_params__", None)
        if params is None or not params.frozen:
            raise NotADataclassError(
                f"a flow's payload must be a frozen dataclass instance, "
                f"got {type(self.data).__name__}"
            )

    def merged(self, delta: Delta) -> State[T]:
        """Return a new state with the delta's fields replaced."""
        # dataclasses.replace needs a dataclass instance. __post_init__ has
        # already established that, which the type system cannot express.
        payload = cast(object, self.data)
        return State(cast(T, dataclasses.replace(payload, **delta)), self.visits)  # type: ignore[type-var]  # payload is a dataclass, checked in __post_init__

    def with_visit(self, node: str) -> State[T]:
        """Return a new state with one more recorded visit to `node`."""
        return State(self.data, {**self.visits, node: self.visit_count(node) + 1})

    def visit_count(self, node: str) -> int:
        """How often `node` has run in this state's history."""
        return self.visits.get(node, 0)
