"""Approval points, read back from the journal.

A paused run has an address: the journal's last entry names the gate and the
question it asked, so `resume` needs nothing but the journal.
"""

from __future__ import annotations

from dataclasses import dataclass

from ultraloom.journal import Journal


@dataclass(frozen=True, slots=True)
class PendingGate:
    """A gate that stopped a run and is waiting for an answer."""

    node: str
    question: str


def pending_gate(journal: Journal) -> PendingGate | None:
    """The open question of this run, or None if nothing is waiting."""
    entries = journal.entries()
    if not entries:
        return None
    last = entries[-1]
    if last.outcome != "paused" or last.detail is None:
        return None
    return PendingGate(last.node, last.detail)
