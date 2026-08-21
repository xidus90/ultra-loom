"""Tests for the translation from the model port to the Claude Agent SDK.

The SDK itself is replaced by a stub module, so these tests cover the
translation completely without a network call. A single contract test talks to
the real SDK and stays out of the default run.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ultraloom.model.port import ModelError, Request


@dataclass(frozen=True, slots=True)
class Verdict:
    """The schema a request asks for. Frozen, like every payload in the core."""

    fix: str = ""


@dataclass
class _Options:
    """Stands in for ClaudeAgentOptions, with the fields the adapter fills."""

    tools: list[str] | None = None
    allowed_tools: list[str] = field(default_factory=list)
    permission_mode: str | None = None
    effort: str | None = None
    cwd: str | None = None
    output_format: dict[str, Any] | None = None


@dataclass
class _ResultMessage:
    """Stands in for ResultMessage, with the fields the adapter reads."""

    is_error: bool = False
    subtype: str = "success"
    result: str | None = None
    structured_output: Any = None  # the SDK types it as Any; a stub cannot narrow it
    usage: dict[str, Any] | None = None


@dataclass
class _AssistantMessage:
    """Any message that is not the result. The adapter must walk past it."""

    text: str = "thinking out loud"


class StubSdk:
    """A recording stand-in for the SDK, installed into sys.modules."""

    def __init__(self, module: ModuleType) -> None:
        self.module = module
        self.calls: list[tuple[str, _Options]] = []

    def answers_with(self, *messages: object) -> None:
        """Make the next query yield exactly these messages."""

        async def query(*, prompt: str, options: _Options) -> AsyncIterator[object]:
            self.calls.append((prompt, options))
            for message in messages:
                yield message

        self.module.query = query  # type: ignore[attr-defined]  # a stub module grows its attributes

    def raises(self, error: Exception) -> None:
        """Make the next query fail the way an unreachable service would."""

        async def query(*, prompt: str, options: _Options) -> AsyncIterator[object]:
            self.calls.append((prompt, options))
            raise error
            yield  # pragma: no cover  # unreachable, but it is what makes this a generator

        self.module.query = query  # type: ignore[attr-defined]  # a stub module grows its attributes


@pytest.fixture
def stub_sdk(monkeypatch: pytest.MonkeyPatch) -> StubSdk:
    """Put a recording stand-in for the SDK into sys.modules."""
    module = ModuleType("claude_agent_sdk")
    module.ClaudeAgentOptions = _Options  # type: ignore[attr-defined]  # a stub module grows its attributes
    module.ResultMessage = _ResultMessage  # type: ignore[attr-defined]  # a stub module grows its attributes
    stub = StubSdk(module)
    stub.answers_with(
        _AssistantMessage(),
        _ResultMessage(structured_output={"fix": "patched"}, usage={"output_tokens": 11}),
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    return stub


def a_request(tools: tuple[str, ...] = ("Read", "Grep")) -> Request:
    return Request(prompt="read the report", tools=tools, effort="low", schema=Verdict)


def _ask(cwd: Path, request: Request | None = None) -> Any:
    from ultraloom.model.agent_sdk import AgentSdkModel

    return AgentSdkModel(cwd=cwd).ask(request if request is not None else a_request())


def test_the_adapter_satisfies_the_model_protocol(tmp_path: Path) -> None:
    """Structurally, inheriting nothing — the same way FakeModel does."""
    from ultraloom.model.agent_sdk import AgentSdkModel
    from ultraloom.model.port import Model

    model: Model = AgentSdkModel(cwd=tmp_path)

    assert Model not in AgentSdkModel.__mro__
    assert callable(model.ask)


def test_the_prompt_and_the_tools_reach_the_sdk(stub_sdk: StubSdk, tmp_path: Path) -> None:
    _ask(tmp_path)

    prompt, options = stub_sdk.calls[0]
    assert prompt == "read the report"
    assert options.allowed_tools == ["Read", "Grep"]
    assert options.tools == ["Read", "Grep"]


def test_a_server_wide_mcp_entry_allows_but_does_not_restrict(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    """`mcp__<server>` is an allow rule for a whole server, never a tool name.

    It goes to `allowed_tools` unchanged and is kept out of `tools`, which is
    the ceiling on the *built-in* tools and knows no such name.
    """
    _ask(tmp_path, a_request(tools=("Read", "mcp__docs")))

    _prompt, options = stub_sdk.calls[0]
    assert options.allowed_tools == ["Read", "mcp__docs"]
    assert options.tools == ["Read"]


def test_the_effort_and_the_working_directory_reach_the_sdk(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    _ask(tmp_path)

    _prompt, options = stub_sdk.calls[0]
    assert options.effort == "low"
    assert str(tmp_path) == str(options.cwd)


def test_no_tool_call_is_ever_waited_on_for_an_answer(stub_sdk: StubSdk, tmp_path: Path) -> None:
    """A harness run is unattended: an unapproved tool is denied, not prompted."""
    _ask(tmp_path)

    _prompt, options = stub_sdk.calls[0]
    assert options.permission_mode == "dontAsk"


def test_the_schema_travels_as_a_json_schema(stub_sdk: StubSdk, tmp_path: Path) -> None:
    _ask(tmp_path)

    _prompt, options = stub_sdk.calls[0]
    assert options.output_format == {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {"fix": {"type": "string"}},
            "additionalProperties": False,
        },
    }


def test_every_field_type_the_schema_knows_is_translated(stub_sdk: StubSdk, tmp_path: Path) -> None:
    @dataclass(frozen=True, slots=True)
    class Wide:
        text: str = ""
        count: int = 0
        ratio: float = 0.0
        done: bool = False
        other: Path = Path()

    stub_sdk.answers_with(_ResultMessage(structured_output={}))
    _ask(tmp_path, Request(prompt="p", tools=(), effort="low", schema=Wide))

    _prompt, options = stub_sdk.calls[0]
    assert options.output_format is not None
    properties = options.output_format["schema"]["properties"]
    assert [entry["type"] for entry in properties.values()] == [
        "string",
        "integer",
        "number",
        "boolean",
        "string",
    ]


def test_the_reply_is_built_into_the_schema_and_carries_its_tokens(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    reply = _ask(tmp_path)

    assert reply.value == Verdict(fix="patched")
    assert reply.tokens == 11


def test_a_result_without_usage_costs_nothing_it_can_prove(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    stub_sdk.answers_with(_ResultMessage(structured_output={"fix": "patched"}))

    assert _ask(tmp_path).tokens == 0


def test_a_reply_that_does_not_fit_the_schema_is_a_model_error(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    """A wrong shape must fail loudly here, not corrupt a later node's state."""
    stub_sdk.answers_with(_ResultMessage(structured_output={"unexpected": 1}))

    with pytest.raises(ModelError, match="does not fit"):
        _ask(tmp_path)


def test_a_reply_that_is_not_an_object_at_all_is_a_model_error(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    """No structured output at all reads as prose, and prose has no fields."""
    stub_sdk.answers_with(_ResultMessage(structured_output=None))

    with pytest.raises(ModelError, match="does not fit"):
        _ask(tmp_path)


def test_a_run_that_never_reached_a_result_is_a_model_error(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    stub_sdk.answers_with(_AssistantMessage())

    with pytest.raises(ModelError, match="no result"):
        _ask(tmp_path)


def test_an_error_result_is_a_model_error_naming_what_went_wrong(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    stub_sdk.answers_with(_ResultMessage(is_error=True, result="the model refused"))

    with pytest.raises(ModelError, match="the model refused"):
        _ask(tmp_path)


def test_an_error_result_without_a_message_still_names_its_subtype(
    stub_sdk: StubSdk, tmp_path: Path
) -> None:
    stub_sdk.answers_with(_ResultMessage(is_error=True, subtype="error_max_turns"))

    with pytest.raises(ModelError, match="error_max_turns"):
        _ask(tmp_path)


def test_an_sdk_exception_becomes_a_model_error(stub_sdk: StubSdk, tmp_path: Path) -> None:
    stub_sdk.raises(RuntimeError("the service is unreachable"))

    with pytest.raises(ModelError, match="unreachable"):
        _ask(tmp_path)


def test_a_missing_sdk_is_reported_with_the_install_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)

    with pytest.raises(ModelError, match=r"ultraloom\[agent\]"):
        _ask(tmp_path)


@pytest.mark.contract
def test_the_real_sdk_answers_a_trivial_question(tmp_path: Path) -> None:
    """Runs only with `-m contract`: needs the SDK, the network and credentials."""

    @dataclass(frozen=True, slots=True)
    class Answer:
        capital: str = ""

    reply = _ask(
        tmp_path,
        Request(
            prompt="What is the capital of France? Answer with the city name only.",
            tools=(),
            effort="low",
            schema=Answer,
        ),
    )

    assert isinstance(reply.value, Answer)
    assert reply.tokens > 0
