"""Tests for the model port's stand-in."""

from dataclasses import dataclass

import pytest

from ultraloom.model.fake import FakeModel
from ultraloom.model.port import ModelError, Reply, Request


@dataclass(frozen=True, slots=True)
class Answer:
    ok: bool = True


def a_request(prompt: str = "ask") -> Request:
    return Request(prompt=prompt, tools=("Read",), effort="low", schema=Answer)


def test_replies_come_back_in_the_order_they_were_given() -> None:
    model = FakeModel([Reply(Answer(ok=True), tokens=7), Reply(Answer(ok=False), tokens=9)])

    assert model.ask(a_request()).value == Answer(ok=True)
    assert model.ask(a_request()).value == Answer(ok=False)


def test_the_fake_records_what_it_was_asked() -> None:
    model = FakeModel([Reply(Answer(), tokens=1)])
    model.ask(a_request("check the report"))

    assert [request.prompt for request in model.seen] == ["check the report"]
    assert model.seen[0].tools == ("Read",)


def test_a_queued_error_is_raised_instead_of_returned() -> None:
    model = FakeModel([ModelError("the model is unreachable")])

    with pytest.raises(ModelError, match="unreachable"):
        model.ask(a_request())


def test_running_out_of_replies_is_an_error_not_a_silent_none() -> None:
    model = FakeModel([])

    with pytest.raises(ModelError, match="no reply left"):
        model.ask(a_request())
