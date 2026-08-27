"""Was `toolchain.resolve` findet, und woran es sich nicht festhält."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from ultraloom import toolchain

_WINDOWS = sys.platform == "win32"


def _executable(path: Path, *, content: str = "") -> Path:
    """Eine Datei, die auf POSIX auch startbar wäre."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _local(root: Path, name: str) -> Path:
    return _executable(root / toolchain.LOCAL_DIR / name)


def test_the_variable_name_follows_the_tool_name() -> None:
    assert toolchain.env_var("godot") == "ULTRALOOM_TOOL_GODOT"
    assert toolchain.env_var("gdtoolkit-lint") == "ULTRALOOM_TOOL_GDTOOLKIT_LINT"


def test_the_variable_beats_a_project_local_tool(tmp_path: Path) -> None:
    _local(tmp_path, "godot")
    mine = _executable(tmp_path / "elsewhere" / "godot")

    found = toolchain.resolve(
        "godot", tmp_path, {"ULTRALOOM_TOOL_GODOT": str(mine)}, platform="linux"
    )

    assert found == toolchain.Tool(mine, pinned=True)


def test_a_variable_pointing_at_nothing_falls_through(tmp_path: Path) -> None:
    """Der Kern des Vorbilds: ein toter Pfad wird nicht weitergereicht."""
    local = _local(tmp_path, "godot")

    found = toolchain.resolve(
        "godot",
        tmp_path,
        {"ULTRALOOM_TOOL_GODOT": str(tmp_path / "gone" / "godot")},
        platform="linux",
    )

    assert found == toolchain.Tool(local, pinned=True)


def test_an_empty_variable_counts_as_unset(tmp_path: Path) -> None:
    local = _local(tmp_path, "godot")

    found = toolchain.resolve("godot", tmp_path, {"ULTRALOOM_TOOL_GODOT": "  "}, platform="linux")

    assert found == toolchain.Tool(local, pinned=True)


def test_the_project_local_tool_beats_path(tmp_path: Path) -> None:
    local = _local(tmp_path, "godot")
    on_path = _executable(tmp_path / "bin" / "godot")

    found = toolchain.resolve("godot", tmp_path, {"PATH": str(on_path.parent)}, platform="linux")

    assert found == toolchain.Tool(local, pinned=True)


def test_path_answers_when_nothing_closer_does(tmp_path: Path) -> None:
    # Der Dateiname folgt der Maschine: shutil.which sucht auf Windows nach
    # PATHEXT und findet ein endungsloses `godot` dort nicht -- das ist die
    # Regel des Systems und nicht die dieses Moduls.
    on_path = _executable(tmp_path / "bin" / ("godot.exe" if _WINDOWS else "godot"))

    found = toolchain.resolve("godot", tmp_path, {"PATH": str(on_path.parent)})

    # Nur Verzeichnis und Stamm: which schreibt die Endung so, wie PATHEXT sie
    # führt, also `.EXE` -- die Datei ist dieselbe.
    assert found is not None
    assert (found.path.parent, found.path.stem) == (on_path.parent, "godot")
    assert not found.pinned, "PATH answered, so the bare name already reaches it"


def test_nothing_found_is_none(tmp_path: Path) -> None:
    assert toolchain.resolve("godot", tmp_path, {"PATH": ""}, platform="linux") is None


def test_windows_tries_the_suffixes_in_a_fixed_order() -> None:
    assert toolchain.local_names("godot", "win32") == (
        "godot",
        "godot.exe",
        "godot.cmd",
        "godot.bat",
    )


def test_posix_tries_the_bare_name_only() -> None:
    assert toolchain.local_names("godot", "linux") == ("godot",)


def test_a_windows_suffix_is_found_by_the_walk(tmp_path: Path) -> None:
    """Die reine Funktion allein bewiese nicht, dass der Gang sie benutzt."""
    exe = _local(tmp_path, "godot.exe")

    found = toolchain.resolve("godot", tmp_path, {"PATH": ""}, platform="win32")

    assert found == toolchain.Tool(exe, pinned=True)


def test_the_default_platform_is_this_machine(tmp_path: Path) -> None:
    """Ohne dieses Argument entscheidet sys.platform, nicht ein Vorgabewert."""
    name = "godot.exe" if sys.platform == "win32" else "godot"
    local = _local(tmp_path, name)

    assert toolchain.resolve("godot", tmp_path, {"PATH": ""}) == toolchain.Tool(local, pinned=True)
