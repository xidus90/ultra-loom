"""Translating the model port into a Claude Agent SDK call.

Deliberately thin: everything the harness needs is decided in `runner.py`, so
this file only renames fields, walks the SDK's message stream to its result,
and turns every failure into a ModelError.
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final

from ultraloom.model.port import ModelError, Reply, Request

_MISSING = 'the agent extra is missing; install it with uv add "ultraloom[agent]"'

# `mcp__<server>` is what tools.resolve_tools emits for an MCP server: an allow
# rule covering every tool of that server. The SDK's own tool names carry a
# third segment (`mcp__<server>__<tool>`), which ultraloom cannot know without
# connecting first.
_MCP_PREFIX = "mcp__"

# Every attribute this adapter reads off a ResultMessage. Named here so the
# guard test in test_agent_sdk.py can hold them against the installed SDK;
# the stub the unit tests use declares whatever they ask of it.
RESULT_FIELDS: Final = ("is_error", "subtype", "result", "usage", "structured_output")

# Where a wheel that carries the CLI keeps it, relative to the package root.
BUNDLE_DIR: Final = "_bundled"

_WINDOWS: Final = sys.platform == "win32"

_NO_CLI: Final = (
    "no Claude CLI to start: the installed claude-agent-sdk bundles none and none "
    "was found on PATH. Name one in [agent].cli_path, export ULTRALOOM_CLI_PATH for "
    "this machine, or install Claude Code natively "
    "(irm https://claude.ai/install.ps1 | iex)"
)


def find_cli(cli_path: Path | None = None, *, windows: bool = _WINDOWS) -> Path:
    """The CLI a run would start, or a ModelError saying which way out to take.

    Deliberately a diagnosis and not a second rulebook: it walks the same three
    places the SDK walks, in the same order, and refuses only where all three
    come up empty. Being stricter than the SDK would turn this into a check
    that forbids runs the SDK could have made.
    """
    if cli_path is not None:
        # Its existence is Config's business; what it *is* is this file's,
        # because the reason a .cmd cannot be started is the SDK's reason.
        _reject_batch(cli_path, windows)
        return cli_path
    bundled = bundled_cli(windows=windows)
    if bundled is not None:
        return bundled
    # `claude.exe` first: shutil.which walks PATH directory-major, so an npm
    # shim in an early directory shadows a native executable in a later one.
    for name in ("claude.exe", "claude") if windows else ("claude",):
        found = shutil.which(name)
        if found:
            _reject_batch(Path(found), windows)
            return Path(found)
    raise ModelError(_NO_CLI)


def bundled_cli(*, windows: bool = _WINDOWS) -> Path | None:
    """The CLI inside the installed wheel, if this wheel carries one.

    A platform wheel does; the platform-independent one does not, and that is
    the whole failure this diagnosis exists for.
    """
    package = Path(_sdk().__file__ or ".").parent
    cli = package / BUNDLE_DIR / ("claude.exe" if windows else "claude")
    return cli if cli.is_file() else None


def _reject_batch(cli_path: Path, windows: bool) -> None:
    """Refuse a .cmd/.bat, the way the SDK does, but before a run has begun."""
    if not windows or cli_path.suffix.rstrip(". ").lower() not in (".cmd", ".bat"):
        return
    raise ModelError(
        f"{cli_path} is a batch script, and the agent SDK refuses to start one: "
        "Windows runs .cmd/.bat through cmd.exe, where an argument cannot be "
        "escaped reliably. Name a claude.exe in [agent].cli_path, export "
        "ULTRALOOM_CLI_PATH for this machine, or install Claude Code natively "
        "(irm https://claude.ai/install.ps1 | iex)"
    )


class AgentSdkModel:
    """Reaches the model through Claude Code's own harness.

    Satisfies `Model` structurally and inherits nothing, the same way
    `FakeModel` does — the port is a shape, not a base class.
    """

    def __init__(self, cwd: Path, cli_path: Path | None = None) -> None:
        self._cwd = cwd
        self._cli_path = cli_path

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
        # Inside the try, deliberately: building the options is as much a use
        # of the SDK's surface as calling it, so a renamed field must reach the
        # caller as the ModelError `ask` promises rather than as a TypeError
        # from the middle of a run.
        try:
            options = sdk.ClaudeAgentOptions(**self._options_for(request))
            result = asyncio.run(
                _last_result(sdk.ResultMessage, sdk.query(prompt=request.prompt, options=options))
            )
        except ModelError:
            # A schema this adapter cannot describe is our own refusal, and
            # dressing it as "the agent SDK failed" would send the reader to
            # look for a fault in the SDK.
            raise
        except Exception as error:
            raise ModelError(f"the agent SDK failed: {error}") from error

        if result is None:
            raise ModelError("the agent SDK produced no result message")
        if result.is_error:
            raise ModelError(f"the agent SDK failed: {result.result or result.subtype}")
        usage = result.usage or {}
        return result.structured_output, int(usage.get("output_tokens", 0))

    def _options_for(self, request: Request) -> dict[str, Any]:
        """The option fields this adapter sets, by SDK name.

        A dict rather than the call itself, so `test_agent_sdk.py` can check
        these names against the installed ClaudeAgentOptions without a network
        call — the unit tests run against a stub that would accept anything.
        """
        options: dict[str, Any] = {
            # Two different questions, two different fields: `tools` is the
            # ceiling on the built-in tools, `allowed_tools` decides what runs
            # without asking. An `mcp__<server>` entry is a permission rule and
            # would name no built-in tool, so it goes only into the second.
            "tools": [name for name in request.tools if not name.startswith(_MCP_PREFIX)],
            "allowed_tools": list(request.tools),
            # A harness run is unattended. Anything outside allowed_tools must
            # be denied at once rather than block the run on a prompt nobody
            # is there to answer.
            "permission_mode": "dontAsk",
            "effort": request.effort,
            "cwd": str(self._cwd),
            "output_format": {"type": "json_schema", "schema": _schema_of(request.schema)},
        }
        if self._cli_path is not None:
            # Only when configured. Passing None would hand the SDK an explicit
            # answer where ultraloom has none, and what it makes of that is the
            # SDK's business to change.
            options["cli_path"] = str(self._cli_path)
        return options


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


_JSON_TYPES: Final = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}


def _schema_of(schema: type) -> dict[str, Any]:
    """A JSON-schema-shaped description of a frozen dataclass of scalar fields."""
    fields = dataclasses.fields(schema)
    properties = {field.name: {"type": _json_type(schema, field)} for field in fields}
    # Every field the dataclass does not default is required. Without this the
    # model may omit a mandatory field, `schema(**payload)` fills the default,
    # and a value nobody produced enters the flow state and the journal.
    required = [field.name for field in fields if not _has_default(field)]
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _has_default(field: dataclasses.Field[Any]) -> bool:
    return (
        field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
    )


def _json_type(schema: type, field: dataclasses.Field[Any]) -> str:
    """The JSON type for one field, or a refusal.

    Deliberately not a fallback to "string": dataclasses do not check field
    types, so a `list[str]` described as a string would be accepted by
    `schema(**payload)` and carry a wrong-typed value into the state and the
    journal with nothing raising anywhere.
    """
    annotation = field.type
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    if text not in _JSON_TYPES:
        raise ModelError(
            f"{schema.__name__}.{field.name}: ultraloom cannot describe {text or annotation!r} "
            "to the model; a schema is a frozen dataclass of str, int, float and bool fields"
        )
    return _JSON_TYPES[text]
