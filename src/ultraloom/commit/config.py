"""What [commit] in .ultraloom/config.toml means.

Unlike [policy.*], this section has no built-in rule that applies without it:
there is no sensible default language to check a commit message against, so a
project that never writes the section gets no check at all.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ultraloom.commit.language import LANGUAGES, Language
from ultraloom.config import CONFIG_NAME, ConfigError

# The threshold below which a stopword hit is noise rather than a signal --
# see language.py's own note on how the English direction was calibrated.
DEFAULT_THRESHOLD = 2


@dataclass(frozen=True, slots=True)
class CommitPolicy:
    """What a project decided about the language of its commit messages."""

    language: Language
    threshold: int
    allow: tuple[re.Pattern[str], ...]


def load_commit_policy(root: Path) -> CommitPolicy | None:
    """This project's [commit] section, or None if it never wrote one.

    None and not defaults: [policy.*] has security rules that protect a
    project which configured nothing, but there is nothing here that holds
    without a language having been chosen first.
    """
    path = root / CONFIG_NAME
    if not path.is_file():
        return None

    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error

    if "commit" not in raw:
        return None
    commit = raw["commit"]
    if not isinstance(commit, dict):
        raise ConfigError(f"{path}: [commit] must be a table")

    language = commit.get("language")
    if language is None:
        # Deliberately no default: a section that names no language has not
        # decided one, and a guessed default would refuse commits against a
        # rule nobody chose.
        raise ConfigError(f"{path}: [commit] needs a `language`")
    if language not in LANGUAGES:
        raise ConfigError(f"{path}: [commit].language must be one of {LANGUAGES}")

    threshold = commit.get("threshold", DEFAULT_THRESHOLD)
    # TOML's booleans are Python ints, and `threshold = true` is nobody's
    # intent -- the same trap [verify].timeout has in policy/config.py's sibling.
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        raise ConfigError(f"{path}: [commit].threshold must be an integer")
    if threshold <= 0:
        raise ConfigError(f"{path}: [commit].threshold must be greater than zero")

    raw_allow = commit.get("allow", [])
    if not isinstance(raw_allow, list) or not all(isinstance(item, dict) for item in raw_allow):
        raise ConfigError(f"{path}: [[commit.allow]] must be a list of tables")
    allow = tuple(_allow(item, path, index) for index, item in enumerate(raw_allow))

    return CommitPolicy(language=language, threshold=threshold, allow=allow)


def _allow(item: Mapping[str, Any], path: Path, index: int) -> re.Pattern[str]:
    """One [[commit.allow]] entry, compiled so a bad regex fails while reading.

    Checked here and not at the first match: a run against several commits
    would otherwise let which one is refused first decide whether the broken
    pattern is ever seen.
    """
    where = f"[[commit.allow]] #{index + 1}"

    # No `match`: the policy's path rules take a glob there, but a glob has no
    # clear meaning against a line of text -- does "WIP*" mean the whole line
    # or somewhere in it? A regex says exactly what it matches, so it is the
    # only key here, and writing `match` is refused rather than silently
    # compiled as a regex, where "WIP*" would quietly become "WIP" followed by
    # zero or more "P".
    if "match" in item:
        raise ConfigError(
            f"{path}: {where} has no `match` -- remove it and write a `regex`; unlike "
            "the policy's path rules a glob has no clear meaning against a line of text"
        )
    if "regex" not in item:
        raise ConfigError(
            f"{path}: {where} needs a `regex`; unlike the policy's path rules there is "
            "no `match`, because a glob has no clear meaning against a line of text"
        )

    reason = item.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ConfigError(f"{path}: {where} needs a `reason`")

    pattern = item["regex"]
    if not isinstance(pattern, str):
        raise ConfigError(f"{path}: {where} must be a string")
    try:
        return re.compile(pattern)
    except re.error as error:
        raise ConfigError(f"{path}: {where}: invalid regex: {error}") from error
