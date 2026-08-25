"""What survives between two hook calls, and what happens when it does not."""

from __future__ import annotations

from pathlib import Path

from ultraloom.hooks.state import STATE_DIR, SessionState, read, write


def test_an_unknown_session_starts_at_zero(tmp_path: Path) -> None:
    assert read(tmp_path, "s1") == SessionState(blocks=0, snapshots={})


def test_what_is_written_comes_back(tmp_path: Path) -> None:
    write(tmp_path, "s1", SessionState(blocks=2, snapshots={"a1": "deadbeef"}))
    assert read(tmp_path, "s1") == SessionState(blocks=2, snapshots={"a1": "deadbeef"})


def test_two_sessions_do_not_share_a_counter(tmp_path: Path) -> None:
    """Two sessions in one checkout must not reset each other's gate."""
    write(tmp_path, "s1", SessionState(blocks=3, snapshots={}))
    write(tmp_path, "s2", SessionState(blocks=1, snapshots={}))
    assert read(tmp_path, "s1").blocks == 3
    assert read(tmp_path, "s2").blocks == 1


def test_it_lands_under_the_state_dir(tmp_path: Path) -> None:
    write(tmp_path, "s1", SessionState(blocks=1, snapshots={}))
    assert (tmp_path / STATE_DIR / "s1.json").is_file()


def test_a_broken_state_file_reads_as_empty(tmp_path: Path) -> None:
    """A damaged counter must not lock a session out of its own gate.

    Reading it as "nothing blocked yet" costs at most three extra rounds;
    raising here would end every turn with an internal error instead.
    """
    path = tmp_path / STATE_DIR / "s1.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert read(tmp_path, "s1") == SessionState(blocks=0, snapshots={})


def test_a_session_id_with_a_path_separator_is_refused(tmp_path: Path) -> None:
    """The id comes from outside; it must not choose where the file lands."""
    write(tmp_path, "../escape", SessionState(blocks=1, snapshots={}))
    assert not (tmp_path.parent / "escape.json").exists()
    assert (tmp_path / STATE_DIR).is_dir()


def test_a_state_file_of_the_wrong_shape_reads_as_empty(tmp_path: Path) -> None:
    """Valid JSON is not yet a valid state: the fields must have the right types.

    Trusting a counter that is a string would carry the wrong type on into the
    gate, where it fails far from the file that caused it.
    """
    path = tmp_path / STATE_DIR / "s1.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"blocks": "two", "snapshots": {}}', encoding="utf-8")
    assert read(tmp_path, "s1") == SessionState(blocks=0, snapshots={})
