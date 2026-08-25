"""The [commit] section, and what happens when it is wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from ultraloom.commit.config import load_commit_policy
from ultraloom.config import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_no_config_file_means_no_policy(tmp_path: Path) -> None:
    assert load_commit_policy(tmp_path) is None


def test_no_commit_section_means_no_policy(tmp_path: Path) -> None:
    """Opt-in: a project without a language rule gets no check."""
    root = _write(tmp_path, '[verify]\nlint = "ruff check ."\n')
    assert load_commit_policy(root) is None


def test_a_language_alone_is_enough(tmp_path: Path) -> None:
    root = _write(tmp_path, '[commit]\nlanguage = "en"\n')
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.language == "en"
    assert policy.threshold == 2


def test_the_threshold_can_be_raised(tmp_path: Path) -> None:
    root = _write(tmp_path, '[commit]\nlanguage = "en"\nthreshold = 3\n')
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.threshold == 3


def test_allow_patterns_are_compiled(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[commit]
language = "en"

[[commit.allow]]
regex  = "^Quelle:"
reason = "Zitierte Quelle, keine Prosa."
""")
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.allow[0].search("Quelle: der Bericht") is not None


def test_an_allow_regex_matches_what_it_names(tmp_path: Path) -> None:
    """Positive coverage for the accepted shape, not only its error cases."""
    root = _write(tmp_path, """
[commit]
language = "en"

[[commit.allow]]
regex  = "^Co-Authored-By:"
reason = "Trailer, not prose."
""")
    policy = load_commit_policy(root)
    assert policy is not None
    assert policy.allow[0].search("Co-Authored-By: Someone <someone@example.com>") is not None
    assert policy.allow[0].search("Not a trailer line") is None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[commit]\nlanguage = "fr"', "must be one of"),
        ("[commit]\nlanguage = 1", "must be one of"),
        ('[commit]\nlanguage = "en"\nthreshold = "zwei"', "must be an integer"),
        ('[commit]\nlanguage = "en"\nthreshold = 0', "must be greater than zero"),
        ('[commit]\nlanguage = "en"\nthreshold = true', "must be an integer"),
        ('[commit]\nthreshold = 2', "needs a `language`"),
        ('[commit]\nlanguage = "en"\n[[commit.allow]]\nregex = "["\nreason = "x"',
         "invalid regex"),
        ('[commit]\nlanguage = "en"\n[[commit.allow]]\nregex = "^x"', "needs a `reason`"),
        (
            '[commit]\nlanguage = "en"\n[[commit.allow]]\nreason = "x"',
            "needs a `regex`; unlike the policy's path rules there is no `match`",
        ),
        ('commit = "no table"', r"\[commit\] must be a table"),
        (
            '[commit]\nlanguage = "en"\n[[commit.allow]]\n'
            'match = "a"\nreason = "x"',
            "has no `match` -- remove it and write a `regex`",
        ),
        (
            '[commit]\nlanguage = "en"\n[[commit.allow]]\n'
            'match = "a"\nregex = "^b"\nreason = "x"',
            "has no `match` -- remove it and write a `regex`",
        ),
        ('[commit]\nlanguage = "en"\nallow = "no list"', "must be a list of tables"),
        (
            '[commit]\nlanguage = "en"\n[[commit.allow]]\nregex = 1\nreason = "x"',
            "must be a string",
        ),
        # Unreadable TOML is a schema error too: it must name the file rather
        # than escape as a TOMLDecodeError past every ConfigError handler.
        ("[commit", r"config\.toml"),
    ],
)
def test_a_broken_schema_is_refused_by_name(tmp_path: Path, body: str, message: str) -> None:
    root = _write(tmp_path, body)
    with pytest.raises(ConfigError, match=message):
        load_commit_policy(root)
