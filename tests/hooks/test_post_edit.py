"""What the file that was just written gets told about itself."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from ultraloom import process
from ultraloom.hooks.post_edit import formats, run

# The interpreter running the tests, as a command a check can be configured
# with. as_posix(), because config.py splits commands with shlex in POSIX mode
# and would eat a Windows path's backslashes.
_PYTHON = Path(sys.executable).as_posix()


def _payload(tool: str, path: Path, key: str = "file_path") -> io.StringIO:
    return io.StringIO(
        json.dumps(
            {
                "session_id": "s1",
                "hook_event_name": "PostToolUse",
                "tool_name": tool,
                "tool_input": {key: str(path)},
            }
        )
    )


def _config(root: Path, body: str) -> None:
    (root / ".ultraloom").mkdir(parents=True, exist_ok=True)
    (root / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")


def _project(root: Path, *, lint: str = "-c pass", types: str = "-c pass") -> None:
    """A project whose `edit` profile resolves to two commands that we choose."""
    # TOML literal strings ('...'): a command carries double quotes of its own,
    # and in a basic string every one of them would have to be escaped.
    _config(
        root,
        f"[verify]\nlint = '{_PYTHON} {lint}'\ntypes = '{_PYTHON} {types}'\n"
        '\n[verify.profiles]\nedit = ["lint", "types"]\n',
    )


def _fails(message: str) -> str:
    """A python -c command that prints something and exits red.

    Double quotes throughout, escaped for shlex: the command sits in a TOML
    literal string, where a single quote would end the value early.
    """
    return f'-c "print(\\"{message}\\"); raise SystemExit(1)"'


def _written(root: Path, name: str = "a.txt") -> Path:
    """A file the hook will look at. Not Python by default, so no formatter runs."""
    path = root / name
    path.write_text("hello\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.py", True), ("a.pyi", True), ("a.ipynb", False), ("a.md", False), ("a", False)],
)
def test_only_python_is_formatted(name: str, expected: bool) -> None:
    """A formatter that does not understand the file damages it.

    `.ipynb` is JSON; ruff format would not leave a notebook intact.
    """
    assert formats(Path(name)) is expected


def test_a_clean_file_says_nothing(tmp_path: Path) -> None:
    _project(tmp_path)
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path)), tmp_path, errors) == 0
    assert errors.getvalue() == ""


def test_a_notebook_path_is_read_as_well(tmp_path: Path) -> None:
    """NotebookEdit names its file under a key of its own."""
    _project(tmp_path)
    errors = io.StringIO()
    written = _written(tmp_path, "a.ipynb")

    assert run(_payload("NotebookEdit", written, key="notebook_path"), tmp_path, errors) == 0


def test_a_payload_without_a_path_does_nothing(tmp_path: Path) -> None:
    payload = io.StringIO(
        json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {}})
    )
    errors = io.StringIO()

    assert run(payload, tmp_path, errors) == 0


def test_a_tool_input_that_is_not_an_object_does_nothing(tmp_path: Path) -> None:
    payload = io.StringIO(
        json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": "ls"})
    )
    errors = io.StringIO()

    assert run(payload, tmp_path, errors) == 0


def test_a_file_outside_the_project_is_left_alone(tmp_path: Path) -> None:
    """The hook runs a project's checks; a file elsewhere is not its business."""
    outside = tmp_path.parent / "elsewhere.py"
    errors = io.StringIO()

    assert run(_payload("Write", outside), tmp_path, errors) == 0


def test_an_unreadable_payload_is_an_internal_error(tmp_path: Path) -> None:
    errors = io.StringIO()

    assert run(io.StringIO("nonsense"), tmp_path, errors) == 1


def test_a_broken_config_is_an_internal_error(tmp_path: Path) -> None:
    """Exit 1, not 2: a broken [verify] table is not the written file's fault."""
    _config(tmp_path, "[verify\n")
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path)), tmp_path, errors) == 1
    assert "post-edit" in errors.getvalue()


def test_a_project_without_the_edit_profile_says_so(tmp_path: Path) -> None:
    """Exit 1 and a name, never a silent 0.

    A hook that shrugs at a missing profile reports "nothing wrong" about a
    file nothing looked at -- the one failure this whole chain exists to rule
    out. Exit 2 would be wrong the other way: it is not a finding about the
    file.
    """
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path)), tmp_path, errors) == 1
    assert "'edit'" in errors.getvalue()
    assert "profiles: none" in errors.getvalue()


def test_a_red_check_is_a_finding(tmp_path: Path) -> None:
    _project(tmp_path, lint=_fails("bad line"))
    errors = io.StringIO()

    assert run(_payload("Edit", _written(tmp_path)), tmp_path, errors) == 2
    assert "lint" in errors.getvalue()
    assert "bad line" in errors.getvalue()


def test_every_red_check_is_reported_not_just_the_first(tmp_path: Path) -> None:
    """Half a list of findings costs the next round; the policy reports the same way."""
    _project(tmp_path, lint=_fails("lint said"), types=_fails("types said"))
    errors = io.StringIO()

    assert run(_payload("Edit", _written(tmp_path)), tmp_path, errors) == 2
    assert "lint said" in errors.getvalue()
    assert "types said" in errors.getvalue()


def test_a_check_that_cannot_run_at_all_is_an_internal_error(tmp_path: Path) -> None:
    """A chain that cannot run is no finding about the file."""
    # No marker file, and `types` configured nowhere: it resolves to nothing.
    _config(
        tmp_path,
        f'[verify]\nlint = "{_PYTHON} -c pass"\n\n[verify.profiles]\nedit = ["lint", "types"]\n',
    )
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path)), tmp_path, errors) == 1
    assert "types" in errors.getvalue()


def test_a_cycle_in_the_check_order_is_an_internal_error(tmp_path: Path) -> None:
    """The scheduler is the first reader of the *effective* order, so it reports last.

    Half the ring comes from the project and half from the Python preset
    (`coverage after test`), which is why the config loader passes it.
    """
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    _config(
        tmp_path,
        '[verify.after]\ntest = "coverage"\n\n[verify.profiles]\nedit = ["test", "coverage"]\n',
    )
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path)), tmp_path, errors) == 1
    assert "cycle" in errors.getvalue()


def _recorder(
    calls: list[tuple[str, ...]], returncode: int = 0
) -> Callable[..., process.Completed]:
    def fake_run(argv: Sequence[str], *, cwd: Path, timeout: float) -> process.Completed:
        calls.append(tuple(argv))
        return process.Completed(returncode, "", "formatter said no")

    return fake_run


def test_a_python_file_is_formatted_before_it_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(
        tmp_path,
        f'[verify]\nlint = "{_PYTHON} -c pass"\ntypes = "{_PYTHON} -c pass"\n'
        '\n[exec]\nprefix = "docker run x"\n'
        '\n[verify.profiles]\nedit = ["lint", "types"]\n',
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(process, "run", _recorder(calls))
    written = _written(tmp_path, "a.py")
    errors = io.StringIO()

    assert run(_payload("Write", written), tmp_path, errors) == 0
    formatter = next(argv for argv in calls if "format" in argv)
    # Through the same exec prefix as every other command: a project that
    # checks across a container boundary must format on the same side of it.
    assert formatter[:3] == ("docker", "run", "x")
    assert formatter[-1] == str(written)


def test_a_formatter_that_fails_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The formatter refusing is a broken tool, not a finding about the file."""
    _project(tmp_path)
    monkeypatch.setattr(process, "run", _recorder([], returncode=1))
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path, "a.py")), tmp_path, errors) == 1
    assert "formatter said no" in errors.getvalue()


def test_a_formatter_that_cannot_be_started_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)

    def explode(argv: Sequence[str], *, cwd: Path, timeout: float) -> process.Completed:
        raise OSError("no such tool")

    monkeypatch.setattr(process, "run", explode)
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path, "a.py")), tmp_path, errors) == 1
    assert "no such tool" in errors.getvalue()


def test_a_formatter_that_never_finishes_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook that runs after every write must not inherit a hung tool's wait."""
    _project(tmp_path)

    def hang(argv: Sequence[str], *, cwd: Path, timeout: float) -> process.Completed:
        return process.Completed(0, "", "", timed_out=True)

    monkeypatch.setattr(process, "run", hang)
    errors = io.StringIO()

    assert run(_payload("Write", _written(tmp_path, "a.py")), tmp_path, errors) == 1
    assert "timed out" in errors.getvalue()
