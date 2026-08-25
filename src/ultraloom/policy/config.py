"""What [policy.*] in .ultraloom/config.toml means.

The built-in rules live as a constant in this module and not in a shipped TOML
file: a file can go missing, a constant cannot.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ultraloom.config import CONFIG_NAME, ConfigError
from ultraloom.policy.rules import KINDS, Kind, Mode, Rule, RuleGroup, Ruleset

# Security only. `git push` or `pip` instead of `uv` are house rules and belong
# in the project file where they can be seen -- a built-in rule nobody reads
# gets killed with defaults=false at the first friction, taking the real ones
# with it.
DEFAULTS: Mapping[Kind, tuple[Rule, ...]] = {
    "paths": (
        Rule(
            patterns=(
                ".env",
                ".env.*",
                "*.pem",
                "*.key",
                "id_rsa*",
                "*.p12",
                ".npmrc",
                ".pypirc",
                "credentials.json",
                ".aws/**",
            ),
            reason="secrets are not written by an agent",
            is_regex=False,
            tools=None,
        ),
    ),
    "content": (
        Rule(
            patterns=(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                r"\bAKIA[0-9A-Z]{16}\b",
                r"\bsk-[A-Za-z0-9]{20,}\b",
            ),
            reason="this looks like a credential in plain text",
            is_regex=True,
            tools=None,
        ),
    ),
    "commands": (),
}


def load_ruleset(root: Path) -> Ruleset:
    """This project's rules, together with the built-in ones.

    With no file at all only the defaults apply: a repo without configuration
    is protected without anyone having set anything up.
    """
    path = root / CONFIG_NAME
    raw: Mapping[str, Any] = {}
    # is_file() and not exists(): a *directory* of that name would raise past
    # every ConfigError handler on the way out.
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(f"{path}: {error}") from error

    policy = raw.get("policy", {})
    if not isinstance(policy, dict):
        raise ConfigError(f"{path}: [policy] must be a table")

    for name in policy:
        # Caught here rather than ignored: a typo in the heading would
        # otherwise read as "this project configured nothing".
        if name not in KINDS:
            raise ConfigError(f"{path}: unknown policy kind [policy.{name}]")

    groups: dict[Kind, RuleGroup] = {}
    for kind in KINDS:
        table = policy.get(kind, {})
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: [policy.{kind}] must be a table")
        groups[kind] = _group(kind, table, path)
    return Ruleset(groups=groups)


def _group(kind: Kind, table: Mapping[str, Any], path: Path) -> RuleGroup:
    """One [policy.<kind>] section: mode, defaults, own rules."""
    raw_mode = table.get("mode", "deny")
    if raw_mode not in ("deny", "allow"):
        raise ConfigError(f'{path}: [policy.{kind}].mode must be "deny" or "allow"')

    defaults = table.get("defaults", True)
    # TOML has real booleans; `defaults = 1` is nobody's intent and must not
    # switch the protection off.
    if not isinstance(defaults, bool):
        raise ConfigError(f"{path}: [policy.{kind}].defaults must be true or false")

    raw_rules = table.get("rules", [])
    if not isinstance(raw_rules, list) or not all(isinstance(item, dict) for item in raw_rules):
        raise ConfigError(f"{path}: [[policy.{kind}.rules]] must be a list of tables")

    # Defaults first: the order of the messages is the order in which one reads
    # the configuration. Under "allow" they contribute nothing -- there only
    # what is permitted counts -- so they are left out.
    built_in = DEFAULTS[kind] if defaults and raw_mode == "deny" else ()
    rules = built_in + tuple(
        _rule(kind, item, path, index) for index, item in enumerate(raw_rules)
    )
    return RuleGroup(mode=_mode(raw_mode), rules=rules)


def _mode(value: str) -> Mode:
    """Narrowing for mypy only: the value was checked one line earlier."""
    return "allow" if value == "allow" else "deny"


def _rule(kind: Kind, item: Mapping[str, Any], path: Path, index: int) -> Rule:
    """A single rule, with a message that names where it sits."""
    where = f"[[policy.{kind}.rules]] #{index + 1}"

    has_match = "match" in item
    has_regex = "regex" in item
    if has_match and has_regex:
        raise ConfigError(f"{path}: {where} carries both `match` and `regex`; use exactly one")
    if not has_match and not has_regex:
        raise ConfigError(f"{path}: {where} needs `match` or `regex`")

    patterns = _patterns(item["regex"] if has_regex else item["match"], path, where)

    reason = item.get("reason")
    if not isinstance(reason, str) or not reason:
        # A block without a reason produces exactly the kind of message an
        # agent argues with or works around.
        raise ConfigError(f"{path}: {where} needs a `reason`")

    raw_tools = item.get("tools")
    if raw_tools is not None and (
        not isinstance(raw_tools, list) or not all(isinstance(name, str) for name in raw_tools)
    ):
        raise ConfigError(f"{path}: {where}.tools must be a list of strings")
    tools = None if raw_tools is None else frozenset(raw_tools)

    try:
        return Rule(patterns=patterns, reason=reason, is_regex=has_regex, tools=tools)
    except ValueError as error:
        raise ConfigError(f"{path}: {where}: {error}") from error


def _patterns(raw: object, path: Path, where: str) -> tuple[str, ...]:
    """A string or a list of them, never anything else and never empty."""
    if isinstance(raw, str):
        values: Sequence[str] = (raw,)
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        values = raw
    else:
        raise ConfigError(f"{path}: {where} must be a string or a list of strings")
    if not values:
        # An empty list would look like a block and be none.
        raise ConfigError(f"{path}: {where} names no pattern")
    return tuple(values)
