"""The run journal: one JSONL line per node.

Deliberately one thing instead of two — the same file is the log you read to
evaluate a run and the only source a resume reads from.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class JournalError(ValueError):
    """Raised for a journal file that cannot be read or written."""


def _unserializable(value: object) -> object:
    """Refuse a value JSON cannot express, instead of inventing one for it.

    The tempting fallback is `repr`, but a default `repr` carries the object's
    memory address: the same payload would hash differently in a new process, so
    a resume would silently redo finished work — and a collision would silently
    skip a node. Both are invisible, so the journal says so at write time.
    """
    raise JournalError(f"cannot serialize a value of type {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class Entry:
    """What one node did."""

    node: str
    kind: str
    input_hash: str
    delta: Mapping[str, object]
    outcome: str
    tools: str | None
    effort: str | None
    tokens: int
    seconds: float
    detail: str | None


def input_hash(node: str, data: object) -> str:
    """A stable fingerprint of the input a node saw.

    Keys are sorted, so a hash never depends on field ordering — a resume that
    turned on dict order would replay the wrong node without saying so. Python's
    own `hash()` is salted per process and deliberately not used here.

    Raises:
        JournalError: if the payload holds a value JSON cannot express.
    """
    payload: object = data
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        payload = dataclasses.asdict(data)
    blob = json.dumps({"node": node, "data": payload}, sort_keys=True, default=_unserializable)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Journal:
    """Append-only JSONL, read back whole."""

    path: Path

    def append(self, entry: Entry) -> None:
        """Add one line. Creates the file and its parents on first write.

        Raises:
            JournalError: if the entry holds a value JSON cannot express. It is
                refused before the file is touched, so a bad entry leaves no
                half-written line behind.
        """
        line = json.dumps(dataclasses.asdict(entry), sort_keys=True, default=_unserializable)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # LF regardless of platform: the journal is a data format whose bytes a
        # resume and the golden-journal test compare, not a text document.
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    def entries(self) -> tuple[Entry, ...]:
        """Every line, in order. An absent file reads as empty."""
        if not self.path.exists():
            return ()
        found: list[Entry] = []
        text = self.path.read_text(encoding="utf-8", newline="\n")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                found.append(Entry(**json.loads(line)))
            except (json.JSONDecodeError, TypeError) as error:
                message = f"{self.path}: line {number} is not a journal entry"
                raise JournalError(message) from error
        return tuple(found)

    def lookup(self, node: str, node_input_hash: str) -> Entry | None:
        """The most recent entry for this node and this input, if any."""
        for entry in reversed(self.entries()):
            if entry.node == node and entry.input_hash == node_input_hash:
                return entry
        return None
