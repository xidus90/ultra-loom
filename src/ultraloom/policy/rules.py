"""The decision itself: one subject against one ruleset.

No files, no processes, no JSON. Whoever wants to understand the matrix of
mode, defaults and tool filter reads this file and nothing else.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

type Kind = Literal["paths", "commands", "content"]

type Mode = Literal["deny", "allow"]

KINDS: tuple[Kind, ...] = ("paths", "commands", "content")


@dataclass(frozen=True, slots=True)
class Rule:
    """One pattern or several, sharing a single reason."""

    patterns: tuple[str, ...]
    reason: str
    is_regex: bool
    # None means "every tool of this kind" and is not the same as an empty set,
    # which would match no tool at all.
    tools: frozenset[str] | None

    def __post_init__(self) -> None:
        """A broken expression fails when built, not on its first hit.

        Otherwise the message would depend on which file happens to be written
        first -- and a policy that raises while checking does not block, it
        lets through.
        """
        if self.is_regex:
            for pattern in self.patterns:
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"invalid regex {pattern!r}: {error}") from error


@dataclass(frozen=True, slots=True)
class RuleGroup:
    """Every rule of one kind, together with its mode."""

    mode: Mode
    rules: tuple[Rule, ...]


@dataclass(frozen=True, slots=True)
class Ruleset:
    """What a project says in total. A missing kind stops nothing."""

    groups: Mapping[Kind, RuleGroup]


@dataclass(frozen=True, slots=True)
class Subject:
    """What is checked: a path, a command line or a piece of content."""

    kind: Kind
    value: str
    tool: str


@dataclass(frozen=True, slots=True)
class Verdict:
    """The answer. `reasons` is empty when allowed."""

    allowed: bool
    reasons: tuple[str, ...]


def evaluate(ruleset: Ruleset, subject: Subject) -> Verdict:
    """Whether this subject may pass, and if not, why not."""
    group = ruleset.groups.get(subject.kind)
    if group is None:
        return Verdict(allowed=True, reasons=())

    matching = tuple(rule for rule in group.rules if _matches(rule, subject))

    if group.mode == "allow":
        # The first hit is enough: a second reason why something is allowed
        # does not change the answer.
        if matching:
            return Verdict(allowed=True, reasons=())
        return Verdict(
            allowed=False,
            reasons=(f'no rule in [policy.{subject.kind}] allows this; mode is "allow"',),
        )

    # Deny: every hit, not just the first. Otherwise the agent clears one reason
    # after another and needs a round per rule.
    if matching:
        return Verdict(allowed=False, reasons=tuple(rule.reason for rule in matching))
    return Verdict(allowed=True, reasons=())


def _matches(rule: Rule, subject: Subject) -> bool:
    """Whether this rule concerns this subject -- tool first, then patterns."""
    if rule.tools is not None and subject.tool not in rule.tools:
        return False
    return any(_hits(pattern, rule.is_regex, subject) for pattern in rule.patterns)


def _hits(pattern: str, is_regex: bool, subject: Subject) -> bool:
    """A single pattern against the value.

    Paths are matched as paths and everything else as flat text: only
    PurePosixPath.full_match knows `**` across directory boundaries, and it
    keeps `config/*` from reaching `config/a/b`. For a command line the same
    rule would be wrong -- the slash in `rm -rf a/b` separates no levels.
    """
    if is_regex:
        return re.search(pattern, subject.value) is not None
    if subject.kind == "paths":
        return PurePosixPath(subject.value).full_match(pattern)
    return fnmatch.fnmatch(subject.value, pattern)
