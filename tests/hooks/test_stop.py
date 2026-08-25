"""Whether a turn may end, and how often it may be told that it may not.

The riskiest hook of the four: exit 2 holds a session. Every test here that
lets the gate block also says how the blocking stops again.
"""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from ultraloom.checks import KINDS, UNAVAILABLE, CheckResult
from ultraloom.config import Config, ConfigError
from ultraloom.hooks.state import SessionState
from ultraloom.hooks.state import read as read_state
from ultraloom.hooks.state import write as write_state
from ultraloom.hooks.stop import MARKER, MAX_BLOCKS, Chain, run
from ultraloom.worktree import WorktreeError, head_commit


def _payload(session: str = "s1") -> io.StringIO:
    return io.StringIO(json.dumps({"session_id": session, "hook_event_name": "Stop"}))


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _repo(tmp_path: Path) -> Path:
    """A real repository with one commit -- never a stand-in for git."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    (work / "a.py").write_text('"""One."""\n', encoding="utf-8")
    _git(work, "add", "a.py")
    _git(work, "commit", "-m", "first")
    return work


def _green(_kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
    return (CheckResult("lint", True, "", "preset"),)


def _red(_kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
    return (
        CheckResult("lint", False, "a.py:1 unused import", "preset"),
        CheckResult("types", False, "a.py:2 needs a type", "preset"),
    )


def _unavailable(_kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
    return (CheckResult("types", False, "no mypy anywhere", UNAVAILABLE),)


def _dirty(_root: Path, _base: str | None) -> tuple[str, ...]:
    return ("a.py",)


def _clean(_root: Path, _base: str | None) -> tuple[str, ...]:
    return ()


def _never_differ(_root: Path, _base: str | None) -> tuple[str, ...]:
    raise AssertionError("the working tree must not be read at this point")


def _never_chain(_kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
    raise AssertionError("the chain must not run at this point")


def test_the_marker_switches_the_gate_off(tmp_path: Path) -> None:
    """Nothing is read and nothing is run: the human already decided."""
    marker = tmp_path / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _never_differ, _never_chain) == 0


def test_a_project_without_a_claude_directory_does_not_raise(tmp_path: Path) -> None:
    """The marker's parent need not exist; asking for it must not throw."""
    assert not (tmp_path / ".claude").exists()
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _clean, _never_chain) == 0


def test_a_session_that_changed_nothing_is_not_checked(tmp_path: Path) -> None:
    """A turn that only read and answered must not cost forty-five seconds.

    With a base, so the silence is complete: a session that has one gets no
    line at all, and every line the gate does print means something.
    """
    write_state(tmp_path, "s1", SessionState(base="abc123"))
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _clean, _never_chain) == 0
    assert errors.getvalue() == ""


def test_the_counter_stops_blocking_after_three_rounds(tmp_path: Path) -> None:
    """The escalation is the point: a gate that never gives up locks the session."""
    write_state(tmp_path, "s1", SessionState(blocks=MAX_BLOCKS))
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _never_differ, _never_chain) == 0
    assert "gave up" in errors.getvalue()


def test_a_green_chain_lets_the_turn_end(tmp_path: Path) -> None:
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _green) == 0
    assert read_state(tmp_path, "s1").blocks == 0


def test_a_red_chain_blocks_and_names_every_finding(tmp_path: Path) -> None:
    """Every red kind, not just the first -- half a list costs an extra round."""
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _red) == 2
    said = errors.getvalue()
    assert "lint" in said
    assert "types" in said
    assert "needs a type" in said
    assert read_state(tmp_path, "s1").blocks == 1


def test_a_green_turn_does_not_clear_the_counter(tmp_path: Path) -> None:
    """Alternating red and green would otherwise never reach the cap."""
    write_state(tmp_path, "s1", SessionState(blocks=2))
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _green) == 0
    assert read_state(tmp_path, "s1").blocks == 2


def test_a_chain_that_could_not_run_is_not_a_block(tmp_path: Path) -> None:
    """No verdict about the work, so no counting and no exit 2."""
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _unavailable) == 1
    assert "could not run" in errors.getvalue()
    assert "no mypy anywhere" in errors.getvalue()
    assert read_state(tmp_path, "s1").blocks == 0


def test_a_chain_that_refuses_to_be_scheduled_is_an_internal_error(tmp_path: Path) -> None:
    def _cycle(_kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
        raise ConfigError("lint and types wait for each other")

    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _cycle) == 1
    assert "wait for each other" in errors.getvalue()
    assert read_state(tmp_path, "s1").blocks == 0


def test_a_broken_config_is_an_internal_error(tmp_path: Path) -> None:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text("not = = toml", encoding="utf-8")
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _never_chain) == 1


def test_git_refusing_to_answer_is_never_read_as_nothing_changed(tmp_path: Path) -> None:
    def _refuse(_root: Path, _base: str | None) -> tuple[str, ...]:
        raise WorktreeError("not a repository")

    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _refuse, _never_chain) == 1
    assert "not a repository" in errors.getvalue()


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    errors = io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, errors, _never_differ, _never_chain) == 1


def test_a_payload_without_a_session_id_is_an_internal_error(tmp_path: Path) -> None:
    """Without it the counter has nowhere to live, and an uncounted gate never gives up."""
    payload = io.StringIO(json.dumps({"hook_event_name": "Stop"}))
    errors = io.StringIO()
    assert run(payload, tmp_path, errors, _never_differ, _never_chain) == 1


def test_a_red_turn_leaves_the_next_one_with_the_same_question(tmp_path: Path) -> None:
    """Red, then the same state again: the chain must run a second time.

    If the base moved on a block, the next turn would short-circuit and the
    gate would have switched itself off after one finding.
    """
    work = _repo(tmp_path)
    base = head_commit(work)
    write_state(work, "s1", SessionState(base=base))
    (work / "b.py").write_text('"""Two."""\n', encoding="utf-8")

    runs: list[int] = []

    def _counting_red(kinds: Sequence[str], config: Config) -> tuple[CheckResult, ...]:
        runs.append(1)
        return _red(kinds, config)

    assert run(_payload(), work, io.StringIO(), chain=_counting_red) == 2
    assert run(_payload(), work, io.StringIO(), chain=_counting_red) == 2
    assert len(runs) == 2
    assert read_state(work, "s1").base == base
    assert read_state(work, "s1").blocks == 2


def test_a_committed_change_is_still_visible_to_the_gate(tmp_path: Path) -> None:
    """The reason the base exists: `git status` forgets what was committed."""
    work = _repo(tmp_path)
    write_state(work, "s1", SessionState(base=head_commit(work)))
    (work / "b.py").write_text('"""Two."""\n', encoding="utf-8")
    _git(work, "add", "b.py")
    _git(work, "commit", "-m", "second")

    seen: list[int] = []

    def _counting_green(kinds: Sequence[str], config: Config) -> tuple[CheckResult, ...]:
        seen.append(1)
        return _green(kinds, config)

    assert run(_payload(), work, io.StringIO(), chain=_counting_green) == 0
    assert seen == [1]


def test_a_green_turn_moves_the_base_so_the_next_one_is_free(tmp_path: Path) -> None:
    """Green after a commit, then a turn without a change: the second short-circuits."""
    work = _repo(tmp_path)
    write_state(work, "s1", SessionState(base=head_commit(work)))
    (work / "b.py").write_text('"""Two."""\n', encoding="utf-8")
    _git(work, "add", "b.py")
    _git(work, "commit", "-m", "second")

    assert run(_payload(), work, io.StringIO(), chain=_green) == 0
    assert read_state(work, "s1").base == head_commit(work)
    assert run(_payload(), work, io.StringIO(), chain=_never_chain) == 0


def test_without_a_base_the_blind_spot_is_said_out_loud(tmp_path: Path) -> None:
    """A measurement with a known hole must not look like a complete one."""
    work = _repo(tmp_path)
    (work / "b.py").write_text('"""Two."""\n', encoding="utf-8")
    _git(work, "add", "b.py")
    _git(work, "commit", "-m", "second")

    errors = io.StringIO()
    # No base in the state: the committed file is invisible, the tree is clean,
    # and the gate says so instead of reporting a quiet pass.
    assert run(_payload(), work, errors, chain=_never_chain) == 0
    assert "no base commit" in errors.getvalue()


def test_a_green_run_where_the_base_cannot_be_moved_still_ends_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The base cannot be moved on, and that is no reason to hold the turn."""
    import ultraloom.hooks.stop as stop_module

    def _no_head(_root: Path) -> str:
        raise WorktreeError("no commit here")

    monkeypatch.setattr(stop_module, "head_commit", _no_head)
    write_state(tmp_path, "s1", SessionState(base="abc123"))
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _green) == 0
    assert read_state(tmp_path, "s1").base == "abc123"


def test_a_filesystem_that_refuses_the_marker_leaves_the_gate_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused lookup must not end the turn with a traceback.

    Monkeypatched rather than staged on disk: a path long enough or a
    permission strict enough to make `exists()` raise cannot be arranged
    portably, and the branch is there for exactly the case that cannot be
    arranged.
    """

    def _refuse(_self: Path) -> bool:
        raise OSError("name too long")

    monkeypatch.setattr(Path, "exists", _refuse)
    write_state(tmp_path, "s1", SessionState(base="abc123"))
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _clean, _never_chain) == 0


def _red_beside_unavailable(_kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
    return (
        CheckResult("lint", False, "a.py:1 unused import", "preset"),
        CheckResult("types", False, "no mypy anywhere", UNAVAILABLE),
    )


def test_a_real_finding_blocks_even_beside_a_check_that_cannot_run(tmp_path: Path) -> None:
    """The case from a GDScript project: no typechecker exists, lint is genuinely red.

    Such a project carries an unavailable `types` on *every* run. If one
    unavailable result decided the exit code, the gate could never block there:
    it would run the whole chain and let real findings through.
    """
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _red_beside_unavailable) == 2
    said = errors.getvalue()
    assert "unused import" in said
    # Still named: the agent has to see that a kind of check is missing.
    assert "no mypy anywhere" in said
    assert "could not run" not in said
    assert read_state(tmp_path, "s1").blocks == 1


def _profiled(root: Path) -> None:
    """A project whose `edit` profile names the static checks only."""
    (root / ".ultraloom").mkdir(exist_ok=True)
    (root / ".ultraloom" / "config.toml").write_text(
        '[verify.profiles]\nedit = ["lint", "types"]\n', encoding="utf-8"
    )


def _recording(seen: list[tuple[str, ...]]) -> Chain:
    def _chain(kinds: Sequence[str], _config: Config) -> tuple[CheckResult, ...]:
        seen.append(tuple(kinds))
        return (CheckResult("lint", True, "", "preset"),)

    return _chain


def test_a_profile_narrows_what_the_gate_runs(tmp_path: Path) -> None:
    """The measured reason this exists: the suite belongs to the commit, not the turn."""
    _profiled(tmp_path)
    seen: list[tuple[str, ...]] = []
    assert run(_payload(), tmp_path, io.StringIO(), _dirty, _recording(seen), checks="edit") == 0
    assert seen == [("lint", "types")]


def test_a_comma_separated_list_narrows_it_too(tmp_path: Path) -> None:
    """The same spelling `ultraloom run --checks` has, and the same reader behind it."""
    seen: list[tuple[str, ...]] = []
    assert run(_payload(), tmp_path, io.StringIO(), _dirty, _recording(seen), checks="lint") == 0
    assert seen == [("lint",)]


def test_without_the_argument_every_kind_still_runs(tmp_path: Path) -> None:
    """Today's behaviour, unchanged: no profile means the whole chain."""
    seen: list[tuple[str, ...]] = []
    assert run(_payload(), tmp_path, io.StringIO(), _dirty, _recording(seen)) == 0
    assert seen == [KINDS]


def test_an_unknown_profile_never_holds_the_turn(tmp_path: Path) -> None:
    """A broken configuration is not a verdict about the work."""
    errors = io.StringIO()
    assert run(_payload(), tmp_path, errors, _dirty, _never_chain, checks="nope") == 1
    assert "unknown check 'nope'" in errors.getvalue()


def test_a_narrowed_pass_leaves_the_base_where_it_was(tmp_path: Path) -> None:
    """A profile checked part of the work, so the rest must stay in the question.

    Moving the base here would let the next turn treat everything up to this
    commit as verified -- including the suite that never ran.
    """
    work = _repo(tmp_path)
    _profiled(work)
    base = head_commit(work)
    write_state(work, "s1", SessionState(base=base))
    (work / "b.py").write_text('"""Two."""\n', encoding="utf-8")

    assert run(_payload(), work, io.StringIO(), _dirty, _green, checks="edit") == 0
    assert read_state(work, "s1").base == base
