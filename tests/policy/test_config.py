"""The [policy.*] schema, and what happens when it is wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from ultraloom.config import ConfigError
from ultraloom.policy.config import DEFAULTS, load_ruleset
from ultraloom.policy.rules import Subject, evaluate


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_project_without_a_config_still_guards_secrets(tmp_path: Path) -> None:
    """A repo where nobody set anything up is protected anyway."""
    ruleset = load_ruleset(tmp_path)
    assert not evaluate(ruleset, Subject("paths", ".env", "Write")).allowed


def test_the_defaults_cover_the_documented_paths() -> None:
    """What the README promises is what the module holds -- or the two drift."""
    patterns = {pattern for rule in DEFAULTS["paths"] for pattern in rule.patterns}
    assert {
        ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "*.p12",
        ".npmrc", ".pypirc", "credentials.json", ".aws/**",
    } <= patterns


def test_no_command_is_denied_by_default() -> None:
    """`git push` is policy, not security, and belongs in the project file."""
    assert DEFAULTS["commands"] == ()


def test_project_rules_are_added_to_the_defaults(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[[policy.paths.rules]]
match = "uv.lock"
reason = "the lock belongs to uv"
""")
    ruleset = load_ruleset(root)
    assert not evaluate(ruleset, Subject("paths", "uv.lock", "Write")).allowed
    assert not evaluate(ruleset, Subject("paths", ".env", "Write")).allowed


def test_defaults_false_throws_the_built_in_rules_away(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[policy.paths]
defaults = false
""")
    assert evaluate(load_ruleset(root), Subject("paths", ".env", "Write")).allowed


def test_the_defaults_come_first(tmp_path: Path) -> None:
    """The order of the messages is the order in which one reads the file."""
    root = _write(tmp_path, """
[[policy.paths.rules]]
match = ".env"
reason = "the project as well"
""")
    verdict = evaluate(load_ruleset(root), Subject("paths", ".env", "Write"))
    assert verdict.reasons[-1] == "the project as well"
    assert len(verdict.reasons) == 2


def test_allow_mode_beats_the_defaults(tmp_path: Path) -> None:
    """Whoever inverts the mode takes on the responsibility entirely."""
    root = _write(tmp_path, """
[policy.paths]
mode = "allow"

[[policy.paths.rules]]
match = "**"
reason = "everything goes"
""")
    assert evaluate(load_ruleset(root), Subject("paths", ".env", "Write")).allowed


def test_a_tools_filter_is_read(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[[policy.paths.rules]]
match = "docs/**"
tools = ["Write"]
reason = "Write only"
""")
    ruleset = load_ruleset(root)
    assert not evaluate(ruleset, Subject("paths", "docs/a.md", "Write")).allowed
    assert evaluate(ruleset, Subject("paths", "docs/a.md", "Edit")).allowed


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[policy.nowhere]\nmode = "deny"', "unknown policy kind"),
        ('[policy.paths]\nmode = "maybe"', 'must be "deny" or "allow"'),
        ("[policy.paths]\ndefaults = 1", "must be true or false"),
        ('[[policy.paths.rules]]\nreason = "x"', "needs `match` or `regex`"),
        (
            '[[policy.paths.rules]]\nmatch = "a"\nregex = "b"\nreason = "x"',
            "carries both `match` and `regex`",
        ),
        ('[[policy.paths.rules]]\nmatch = []\nreason = "x"', "names no pattern"),
        ('[[policy.paths.rules]]\nmatch = "a"', "needs a `reason`"),
        ('[[policy.paths.rules]]\nmatch = 1\nreason = "x"', "must be a string or a list"),
        (
            '[[policy.paths.rules]]\nmatch = "a"\nreason = "x"\ntools = "Write"',
            "must be a list of strings",
        ),
        ('[[policy.commands.rules]]\nregex = "["\nreason = "x"', "invalid regex"),
        ('[policy.paths]\nrules = "no list"', "must be a list of tables"),
        ('policy = "no table"', r"\[policy\] must be a table"),
        ('[policy]\npaths = "no table"', r"\[policy\.paths\] must be a table"),
        # Unreadable TOML is a schema error too: it must name the file rather
        # than escape as a TOMLDecodeError past every ConfigError handler.
        ("[policy", r"config\.toml"),
    ],
)
def test_a_broken_schema_is_refused_by_name(tmp_path: Path, body: str, message: str) -> None:
    """Every message names the spot the way the file spells it."""
    root = _write(tmp_path, body)
    with pytest.raises(ConfigError, match=message):
        load_ruleset(root)
