"""The decision matrix, case by case."""

from __future__ import annotations

import pytest

from ultraloom.policy.rules import Kind, Mode, Rule, RuleGroup, Ruleset, Subject, evaluate


def _set(kind: Kind, mode: Mode, *rules: Rule) -> Ruleset:
    """Typed rather than str: mypy strict reads the tests too."""
    return Ruleset(groups={kind: RuleGroup(mode=mode, rules=rules)})


def _rule(
    *patterns: str,
    reason: str = "because",
    regex: bool = False,
    tools: frozenset[str] | None = None,
) -> Rule:
    return Rule(patterns=patterns, reason=reason, is_regex=regex, tools=tools)


def test_a_kind_without_rules_allows() -> None:
    """A kind nobody configured stops nothing."""
    verdict = evaluate(Ruleset(groups={}), Subject("paths", "src/a.py", "Write"))
    assert verdict.allowed
    assert verdict.reasons == ()


def test_deny_lets_an_unmatched_path_through() -> None:
    rules = _set("paths", "deny", _rule(".env"))
    assert evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed


def test_deny_stops_a_matching_path_and_says_why() -> None:
    rules = _set("paths", "deny", _rule(".env", reason="no secrets"))
    verdict = evaluate(rules, Subject("paths", ".env", "Write"))
    assert not verdict.allowed
    assert verdict.reasons == ("no secrets",)


def test_deny_collects_every_matching_rule() -> None:
    """All reasons at once: otherwise the agent clears them one round at a time."""
    rules = _set(
        "paths",
        "deny",
        _rule(".env", reason="first"),
        _rule("*.env", reason="second"),
    )
    verdict = evaluate(rules, Subject("paths", ".env", "Write"))
    assert verdict.reasons == ("first", "second")


def test_a_list_of_patterns_shares_one_reason() -> None:
    rules = _set("paths", "deny", _rule(".env", "*.pem", reason="secrets"))
    assert not evaluate(rules, Subject("paths", "server.pem", "Write")).allowed


def test_globs_span_directories_only_with_double_star() -> None:
    """`config/*` must not reach `config/a/b`, or a pattern locks more than it says."""
    rules = _set("paths", "deny", _rule("config/*"))
    assert evaluate(rules, Subject("paths", "config/a/b", "Write")).allowed
    assert not evaluate(rules, Subject("paths", "config/a", "Write")).allowed


def test_a_double_star_reaches_down() -> None:
    rules = _set("paths", "deny", _rule(".aws/**"))
    assert not evaluate(rules, Subject("paths", ".aws/creds/x", "Write")).allowed


def test_commands_match_as_plain_globs_not_as_paths() -> None:
    """A command line is no path: the slash in `rm -rf a/b` separates nothing."""
    rules = _set("commands", "deny", _rule("rm -rf *"))
    assert not evaluate(rules, Subject("commands", "rm -rf a/b", "Bash")).allowed


def test_a_regex_rule_searches_anywhere_in_the_value() -> None:
    rules = _set("commands", "deny", _rule(r"^git\s+push\b", regex=True))
    assert not evaluate(rules, Subject("commands", "git  push --force", "Bash")).allowed
    assert evaluate(rules, Subject("commands", "git pushed", "Bash")).allowed


def test_a_tools_filter_narrows_a_rule() -> None:
    rules = _set("paths", "deny", _rule("docs/**", tools=frozenset({"Write"})))
    assert not evaluate(rules, Subject("paths", "docs/a.md", "Write")).allowed
    assert evaluate(rules, Subject("paths", "docs/a.md", "Edit")).allowed


def test_allow_refuses_everything_it_does_not_name() -> None:
    rules = _set("paths", "allow", _rule("src/**", reason="src only"))
    assert evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed
    denied = evaluate(rules, Subject("paths", "other.py", "Write"))
    assert not denied.allowed
    assert denied.reasons == ('no rule in [policy.paths] allows this; mode is "allow"',)


def test_allow_stops_at_the_first_permission() -> None:
    """A second reason why something is allowed does not change the answer."""
    rules = _set("paths", "allow", _rule("src/**"), _rule("**"))
    assert evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed


def test_allow_with_no_rules_refuses() -> None:
    """An empty allowlist allows nothing -- anything else would be a silent failure."""
    rules = _set("paths", "allow")
    assert not evaluate(rules, Subject("paths", "src/a.py", "Write")).allowed


def test_an_invalid_regex_is_refused_when_the_rule_is_built() -> None:
    with pytest.raises(ValueError, match="invalid regex"):
        Rule(patterns=("[",), reason="x", is_regex=True, tools=None)
