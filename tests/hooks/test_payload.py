"""Reading a hook payload, and refusing what is not one."""

from __future__ import annotations

import io
import json

import pytest

from ultraloom.hooks.payload import PayloadError, read


def test_a_payload_comes_back_as_a_mapping() -> None:
    assert read(io.StringIO(json.dumps({"session_id": "s1"})))["session_id"] == "s1"


@pytest.mark.parametrize("raw", ["", "no json", "[]", "42", '"text"'])
def test_anything_that_is_not_an_object_is_refused(raw: str) -> None:
    with pytest.raises(PayloadError):
        read(io.StringIO(raw))
