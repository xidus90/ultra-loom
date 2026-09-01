"""The adapter between git's hook protocol and the decision in language.py.

A file path and an exit code are all git knows about. Everything this module
adds is the wording of the refusal, which is the whole of its job: a gate whose
message does not say what to change gets routed around with --no-verify.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from ultraloom.commit.config import load_commit_policy
from ultraloom.commit.language import Finding, Language, scan
from ultraloom.config import ConfigError

EXIT_OK = 0
# Not 2 for a broken config: blocking every commit in a repository over a typo
# is the larger harm, and the mistake surfaces at the next `ultraloom check`.
EXIT_INTERNAL = 1
EXIT_WRONG_LANGUAGE = 2

_NAMES = {"en": "English", "de": "German"}

_WAY_OUT = (
    "Rewrite it, or use `git commit --no-verify` if this cannot wait. The next\n"
    "commit runs this check again."
)


def run(path: Path, root: Path, stderr: TextIO) -> int:
    """Check one commit message file. Returns the process exit code."""
    try:
        policy = load_commit_policy(root)
    except ConfigError as error:
        print(f"ultraloom commit-msg: {error}", file=stderr)
        return EXIT_INTERNAL
    if policy is None:
        # Opt-in: a project without a [commit] section never chose a language,
        # so the message is not even read.
        return EXIT_OK

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        # Git wrote this file moments ago, so a failure here is our problem,
        # not the author's -- exit 1 rather than a refusal. A decode failure is
        # one of ours too: UnicodeDecodeError is a ValueError and would escape
        # an OSError-only clause, ending the hook in a pathlib traceback.
        print(f"ultraloom commit-msg: cannot read {path}: {error}", file=stderr)
        return EXIT_INTERNAL

    findings = scan(text, policy.language, policy.threshold, policy.allow)
    if not findings:
        return EXIT_OK

    _report(findings, _NAMES[policy.language], stderr)
    return EXIT_WRONG_LANGUAGE


def _report(findings: tuple[Finding, ...], language: str, stderr: TextIO) -> None:
    """Name every refused line, not just the first one.

    Reporting one at a time would send the author back through the editor once
    per line, and each trip is another chance to reach for --no-verify.
    """
    other = "German" if language == "English" else "English"
    print(
        f"ultraloom commit-msg: this message reads as {other}, and commits here are {language}.",
        file=stderr,
    )
    for finding in findings:
        # The indent comes from the label rather than a constant: a message long
        # enough for a two-digit line number would push the text right and leave
        # a fixed indent pointing at nothing.
        label = f"  line {finding.line_number}: "
        print(f"{label}{finding.line}", file=stderr)
        print(f"{' ' * len(label)}hits: {', '.join(finding.hits)}", file=stderr)
    print(_WAY_OUT, file=stderr)


def calibrate_run(
    root: Path,
    count: int,
    language: Language | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Print what each threshold would have refused in the last `count` commits.

    A measurement, not a gate: the exit code says whether the table could be
    produced, never whether the history would pass.
    """
    # Imported here, like every other import on this module's paths: the hook
    # runs on every commit and must not pay for `git log`'s machinery.
    from ultraloom.commit.calibrate import THRESHOLDS, HistoryError, read_messages, render

    if count < 1:
        # Never handed to git: `git log -n -1` means *unlimited*, and zero
        # prints an empty table. Both answer a typo with something that reads
        # like a measurement, which is the failure this whole gate argues
        # against.
        print(
            f"ultraloom commit-msg: --calibrate needs a count of at least 1, not {count}",
            file=stderr,
        )
        return EXIT_INTERNAL

    try:
        policy = load_commit_policy(root)
    except ConfigError as error:
        print(f"ultraloom commit-msg: {error}", file=stderr)
        return EXIT_INTERNAL

    chosen = language or (None if policy is None else policy.language)
    if chosen is None:
        # No guessed default, for the same reason [commit] has none: the answer
        # would be a measurement against a rule nobody chose.
        print(
            "ultraloom commit-msg: --calibrate needs a language -- pass --language, "
            "or write [commit].language in the config",
            file=stderr,
        )
        return EXIT_INTERNAL

    try:
        messages = read_messages(root, count)
    except HistoryError as error:
        print(f"ultraloom commit-msg: {error}", file=stderr)
        return EXIT_INTERNAL

    # The project's exemptions travel with the measurement: a table that
    # ignored them would report a cost the configured gate never charges.
    allow = () if policy is None else policy.allow
    render(messages, chosen, THRESHOLDS, stdout, allow)
    return EXIT_OK
