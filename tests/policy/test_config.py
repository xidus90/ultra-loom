"""The [policy.*] schema, and what happens when it is wrong."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ultraloom.config import ConfigError
from ultraloom.hooks.state import STATE_DIR
from ultraloom.hooks.stop import MARKER
from ultraloom.policy.config import DEFAULTS, load_ruleset
from ultraloom.policy.rules import Subject, evaluate


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / ".ultraloom").mkdir()
    (tmp_path / ".ultraloom" / "config.toml").write_text(body, encoding="utf-8")
    return tmp_path


README = Path(__file__).resolve().parents[2] / "README.md"
HEADING = "### What a project should add itself"


def _readme_example() -> str:
    """Every toml fence under the heading that carries the examples."""
    section = README.read_text(encoding="utf-8").split(HEADING, 1)
    assert len(section) == 2, f"{README} has no {HEADING!r}"
    # Stop at the next heading of the same level: the fences further down the
    # page document other things and would parse as this project's rules.
    body = re.split(r"\n#{1,3} ", section[1], maxsplit=1)[0]
    blocks = re.findall(r"```toml\n(.*?)```", body, re.DOTALL)
    assert blocks, f"{README}: no toml block under {HEADING!r}"
    return "".join(blocks)


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
match = "docs/generated/**"
reason = "this page is built from the source"
""")
    ruleset = load_ruleset(root)
    assert not evaluate(ruleset, Subject("paths", "docs/generated/api.md", "Write")).allowed
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


def test_the_defaults_protect_the_gate_controls(tmp_path: Path) -> None:
    """The stop gate's own off switch is not something the gated party writes.

    `.claude/.no-verify` carries no counting extension and shows up in no
    change set, so a session that writes it disables the gate for good and
    nothing in the diff says so. Same for the state the gate measures against.
    """
    ruleset = load_ruleset(tmp_path)
    for path in (".claude/.no-verify", ".ultraloom/hooks/some-session.json"):
        assert not evaluate(ruleset, Subject("paths", path, "Write")).allowed, path


def test_the_gate_controls_are_named_by_the_modules_that_own_them() -> None:
    """A renamed marker must not leave the rule pointing at nothing."""
    assert MARKER in {pattern for rule in DEFAULTS["paths"] for pattern in rule.patterns}
    assert f"{STATE_DIR}/**" in {
        pattern for rule in DEFAULTS["paths"] for pattern in rule.patterns
    }


def test_the_defaults_refuse_a_lock_file(tmp_path: Path) -> None:
    """A lock file is the output of a resolver run, not a text to be edited.

    Editing one does not change the project, it changes the claim about the
    project. This holds in every language, which is why the rule is built in.
    """
    ruleset = load_ruleset(tmp_path)
    for path in ("uv.lock", "package-lock.json", "Cargo.lock", "go.sum"):
        assert not evaluate(ruleset, Subject("paths", path, "Write")).allowed, path
        assert not evaluate(ruleset, Subject("paths", path, "Edit")).allowed, path


def test_a_hand_kept_requirements_file_is_not_a_lock_file(tmp_path: Path) -> None:
    """`requirements.txt` is written by hand in many projects.

    A built-in rule there would be the false alarm this group exists to avoid:
    one costs the trust in all the others.
    """
    ruleset = load_ruleset(tmp_path)
    assert evaluate(ruleset, Subject("paths", "requirements.txt", "Write")).allowed


def test_defaults_false_throws_the_lock_rule_away_too(tmp_path: Path) -> None:
    root = _write(tmp_path, """
[policy.paths]
defaults = false
""")
    assert evaluate(load_ruleset(root), Subject("paths", "uv.lock", "Write")).allowed


def test_the_documented_migration_rule_parses_and_matches(tmp_path: Path) -> None:
    """The README's example is run, not just read.

    A documentation suggestion nobody recomputes is a lie in six months -- the
    same argument that carries `test_flow_docs.py`. The block is cut out of the
    page, written as a project configuration and evaluated.
    """
    root = _write(tmp_path, _readme_example())
    ruleset = load_ruleset(root)
    assert not evaluate(
        ruleset, Subject("paths", "apps/core/migrations/0002_add_field.py", "Write")
    ).allowed
    assert evaluate(ruleset, Subject("paths", "apps/core/models.py", "Write")).allowed
