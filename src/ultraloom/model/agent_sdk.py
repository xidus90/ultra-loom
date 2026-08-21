"""Translating the model port into a Claude Agent SDK call.

Deliberately thin: everything the harness needs is decided in `runner.py`, so
this file only renames fields, walks the SDK's message stream to its result,
and turns every failure into a ModelError.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ultraloom.model.port import ModelError, Reply, Request

_MISSING = 'the agent extra is missing; install it with uv add "ultraloom[agent]"'

# `mcp__<server>` is what tools.resolve_tools emits for an MCP server: an allow
# rule covering every tool of that server. The SDK's own tool names carry a
# third segment (`mcp__<server>__<tool>`), which ultraloom cannot know without
# connecting first.
_MCP_PREFIX = "mcp__"


class AgentSdkModel:
    """Reaches the model through Claude Code's own harness.

    Satisfies `Model` structurally and inherits nothing, the same way
    `FakeModel` does — the port is a shape, not a base class.
    """

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def ask(self, request: Request) -> Reply:
        """Answer one request, or raise ModelError."""
        payload, tokens = self._call(request)
        if not isinstance(payload, dict):
            # No structured output at all: the model answered in prose, and
            # prose has no fields. Failing here keeps a later node's state clean.
            raise ModelError(f"the reply does not fit {request.schema.__name__}: {payload!r}")
        try:
            value = request.schema(**payload)
        except TypeError as error:
            raise ModelError(
                f"the reply does not fit {request.schema.__name__}: {payload!r}"
            ) from error
        return Reply(value, tokens)

    def _call(self, request: Request) -> tuple[object, int]:
        """The one place that knows the SDK's surface. Returns payload and cost."""
        sdk = _sdk()
        options = sdk.ClaudeAgentOptions(
            # Two different questions, two different fields: `tools` is the
            # ceiling on the built-in tools, `allowed_tools` decides what runs
            # without asking. An `mcp__<server>` entry is a permission rule and
            # would name no built-in tool, so it goes only into the second.
            tools=[name for name in request.tools if not name.startswith(_MCP_PREFIX)],
            allowed_tools=list(request.tools),
            # A harness run is unattended. Anything outside allowed_tools must
            # be denied at once rather than block the run on a prompt nobody
            # is there to answer.
            permission_mode="dontAsk",
            effort=request.effort,
            cwd=str(self._cwd),
            output_format={"type": "json_schema", "schema": _schema_of(request.schema)},
        )

        try:
            result = asyncio.run(
                _last_result(sdk.ResultMessage, sdk.query(prompt=request.prompt, options=options))
            )
        except Exception as error:
            raise ModelError(f"the agent SDK failed: {error}") from error

        if result is None:
            raise ModelError("the agent SDK produced no result message")
        if result.is_error:
            raise ModelError(f"the agent SDK failed: {result.result or result.subtype}")
        usage = result.usage or {}
        return result.structured_output, int(usage.get("output_tokens", 0))


async def _last_result(result_type: type, stream: AsyncIterator[Any]) -> Any:
    """Drain the SDK's message stream and keep the result message.

    Draining rather than breaking out early: the stream is a subprocess, and
    abandoning it mid-flight would leave the CLI to be torn down by chance.
    """
    last = None
    async for message in stream:
        if isinstance(message, result_type):
            last = message
    return last


def _sdk() -> Any:  # the SDK ships no stubs ultraloom could narrow this against
    # Local import: the Claude Agent SDK is an optional extra, and the check
    # chain must stay usable without it (spec 15.2).
    try:
        import claude_agent_sdk
    except ImportError as error:
        raise ModelError(_MISSING) from error
    return claude_agent_sdk


def _schema_of(schema: type) -> dict[str, Any]:
    """A JSON-schema-shaped description of a frozen dataclass."""
    properties = {
        field.name: {"type": _json_type(field.type)} for field in dataclasses.fields(schema)
    }
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _json_type(annotation: object) -> str:
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "str")
    return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(
        text, "string"
    )
