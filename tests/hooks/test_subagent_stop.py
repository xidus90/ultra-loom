"""What a subagent changed, whether or not its report says so."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from ultraloom import process
from ultraloom.hooks.state import SessionState
from ultraloom.hooks.state import write as write_state
from ultraloom.hooks.subagent_stop import differences, head, new_commits, remote_refs, run, snapshot


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _repo_with_remote(tmp_path: Path) -> Path:
    """A real repository with a real remote, both on disk."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    (work / "a.txt").write_text("one\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-m", "first")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "origin", "HEAD:refs/heads/master")
    return work


def _commit(work: Path, text: str, message: str) -> None:
    (work / "a.txt").write_text(text, encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-m", message)


def _payload(agent_id: str = "a1") -> io.StringIO:
    return io.StringIO(
        json.dumps(
            {
                "session_id": "s1",
                "hook_event_name": "SubagentStop",
                "agent_id": agent_id,
                "agent_type": "general-purpose",
            }
        )
    )


def test_no_snapshot_says_so_rather_than_claiming_nothing_happened(tmp_path: Path) -> None:
    """Without a before, there is no after -- and silence would read as "clean"."""
    work = _repo_with_remote(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert "no snapshot" in out.getvalue()


def test_an_unchanged_remote_is_reported_as_nothing(tmp_path: Path) -> None:
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": remote_refs(work)}))
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert out.getvalue() == ""


def test_a_push_is_reported(tmp_path: Path) -> None:
    """The incident this hook exists for: a push nobody mentioned."""
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": remote_refs(work)}))
    _commit(work, "two\n", "second")
    _git(work, "push", "origin", "HEAD:refs/heads/master")

    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert "origin" in out.getvalue()
    assert "refs/heads/master" in out.getvalue()


def test_a_commit_that_stayed_local_is_reported_too(tmp_path: Path) -> None:
    """A run may commit; the commits should not stay invisible."""
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": snapshot(work)}))
    _commit(work, "two\n", "a commit nobody mentioned")

    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert "a commit nobody mentioned" in out.getvalue()
    assert "origin" not in out.getvalue()


def test_a_snapshot_without_a_head_line_compares_the_remote_only(tmp_path: Path) -> None:
    """An older snapshot -- remote refs and nothing else -- still says something."""
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": remote_refs(work)}))
    _commit(work, "two\n", "second")

    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert out.getvalue() == ""


def test_an_unmoved_head_is_reported_as_nothing(tmp_path: Path) -> None:
    work = _repo_with_remote(tmp_path)
    write_state(work, "s1", SessionState(snapshots={"a1": snapshot(work)}))

    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0
    assert out.getvalue() == ""


def test_differences_names_both_sides() -> None:
    before = "aaa\trefs/heads/master\n"
    after = "bbb\trefs/heads/master\nccc\trefs/heads/topic\n"
    found = differences(before, after)
    assert any("refs/heads/master" in line for line in found)
    assert any("refs/heads/topic" in line for line in found)


def test_a_line_that_is_no_ref_at_all_is_passed_over() -> None:
    """`ls-remote` can print a warning line; it is not a ref and not a finding."""
    assert differences("warning: something\naaa\trefs/heads/x\n", "aaa\trefs/heads/x\n") == ()


def test_differences_notices_a_ref_that_disappeared() -> None:
    """A deleted branch is as much a finding as a new one."""
    before = "aaa\trefs/heads/master\nccc\trefs/heads/topic\n"
    after = "aaa\trefs/heads/master\n"
    found = differences(before, after)
    assert len(found) == 1
    assert "refs/heads/topic" in found[0]


def test_a_repository_without_a_remote_is_not_an_error(tmp_path: Path) -> None:
    work = tmp_path / "solo"
    work.mkdir()
    _git(work, "init")
    out, err = io.StringIO(), io.StringIO()
    assert run(_payload(), work, out, err) == 0


def test_remote_refs_is_empty_when_git_cannot_be_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable remote is no finding about the subagent."""

    def explode(*_args: object, **_kwargs: object) -> process.Completed:
        raise OSError("no git here")

    monkeypatch.setattr(process, "run", explode)
    assert remote_refs(tmp_path) == ""


def test_remote_refs_is_empty_when_the_remote_does_not_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hang(*_args: object, **_kwargs: object) -> process.Completed:
        return process.Completed(
            returncode=0, stdout="aaa\trefs/heads/x\n", stderr="", timed_out=True
        )

    monkeypatch.setattr(process, "run", hang)
    assert remote_refs(tmp_path) == ""


def test_head_is_empty_outside_a_repository(tmp_path: Path) -> None:
    assert head(tmp_path) == ""


def test_new_commits_is_empty_when_the_range_makes_no_sense(tmp_path: Path) -> None:
    work = _repo_with_remote(tmp_path)
    assert new_commits(work, "0" * 40) == ()


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert run(io.StringIO("nonsense"), tmp_path, out, err) == 1
    assert "stdin is not JSON" in err.getvalue()


def test_a_payload_without_an_agent_id_is_an_internal_error(tmp_path: Path) -> None:
    """There is nothing to look a snapshot up under, and that is worth saying."""
    payload = io.StringIO(json.dumps({"session_id": "s1", "hook_event_name": "SubagentStop"}))
    out, err = io.StringIO(), io.StringIO()
    assert run(payload, tmp_path, out, err) == 1
    assert "agent_id" in err.getvalue()
