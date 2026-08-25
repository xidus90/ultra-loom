"""Reading what Claude Code puts on stdin, and the exit codes it reads back.

Shared by all four hooks so the protocol is stated once. What exit 2 *means*
is not shared -- it depends on the event, and each hook says so itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TextIO

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_BLOCKED = 2


class PayloadError(ValueError):
    """Raised when stdin does not carry a hook payload."""


def read(stdin: TextIO) -> Mapping[str, Any]:
    """The payload as a mapping, or a refusal naming why it is not one."""
    try:
        payload = json.loads(stdin.read())
    except json.JSONDecodeError as error:
        raise PayloadError(f"stdin is not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise PayloadError("a hook payload is an object")
    return payload
