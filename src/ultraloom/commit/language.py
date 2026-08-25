"""The decision itself: one text against one word list.

No files, no configuration. Whoever wants to understand what counts as a
finding reads this module and nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

type Language = Literal["en", "de"]

LANGUAGES: tuple[Language, ...] = ("en", "de")

# Function words of the other language that mean nothing in the target one.
# Presence is evidence; a word that is also ordinary English is not, however
# German it feels.
#
# Deliberately absent from the German list, each a normal English word: die,
# war, man, den, hat, in, so, an. "Let the process die in the war room" must
# not be a finding.
#
# The German list is calibrated: in one project's history, a hundred English
# commits against sixteen German ones, and these are the words that separate
# them. The English list is not -- see the spec's "Grenzen".
STOPWORDS: Mapping[Language, frozenset[str]] = {
    # Searched when the target language is English.
    "en": frozenset(
        {
            "der", "das", "dem", "des", "und", "oder", "nicht", "ein", "eine",
            "einen", "einem", "eines", "einer", "sind", "waren", "haben",
            "wird", "wurde", "werden", "mit", "von", "fuer", "ueber", "aus",
            "nach", "ohne", "beim", "zum", "zur", "zu", "auf", "durch",
            "gegen", "dass", "weil", "wenn", "schon", "noch", "jeden", "jede",
            "jeder", "wieder", "statt", "samt", "unter", "zusammen", "heraus",
            "ihn", "fest",
        }
    ),
    # Searched when the target language is German. Function words with no
    # German homograph. Not calibrated against a corpus -- the threshold for
    # this direction is a starting point, not a measurement.
    "de": frozenset(
        {
            "the", "and", "with", "this", "that", "from", "which", "into",
            "there", "their", "would", "should", "could", "because", "while",
            "about", "against", "between", "through", "without", "instead",
            "rather", "still", "already", "every", "each", "again",
        }
    ),
}

# `git commit --verbose` appends the whole diff below this marker, uncommented.
# The diff carries whatever the change touched, so scoring it would refuse
# every commit that goes near prose in the other language.
SCISSORS = re.compile(r"^#\s*-+\s*>8\s*-+")

# Shapes that carry the other language inside an otherwise fine message. All
# four are removed from a line before it is scored, because a gate with false
# positives gets routed around with --no-verify and then protects nothing.
TRAILER = re.compile(r"^[A-Za-z-]+:\s")
CODE_SPAN = re.compile(r"`[^`]*`")
QUOTED_SPAN = re.compile(r"\"[^\"]*\"")
PATH_TOKEN = re.compile(r"\S*(?:[/\\]\S*|\.[A-Za-z0-9]{1,5})(?=\s|$)")

# Words may carry umlauts even where the stopword list spells them out:
# a real German commit writes "fuer" or "für", and both must be found. The
# list is ASCII, so the text is folded to match it -- see _fold.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# The stopword lists are ASCII because this file is. German text is not:
# "für" and "über" are the normal spellings. Folding the text rather than
# doubling every entry keeps one list instead of two that can drift.
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One line that reads as the wrong language, and why."""

    line_number: int
    line: str
    hits: tuple[str, ...]


def scan(
    text: str,
    language: Language,
    threshold: int,
    allow: tuple[re.Pattern[str], ...] = (),
) -> tuple[Finding, ...]:
    """Every line whose stopword count reaches the threshold.

    Per line and not per message: a body listing two page titles in the other
    language is two lines of one hit, not one line of two, and the second
    reading would refuse it.
    """
    stopwords = STOPWORDS[language]
    findings: list[Finding] = []

    for number, line in enumerate(text.splitlines(), start=1):
        if SCISSORS.match(line):
            # Everything below belongs to the diff, not to the message.
            break
        if line.startswith("#"):
            continue
        if any(pattern.search(line) for pattern in allow):
            continue
        hits = _hits(line, stopwords)
        if len(hits) >= threshold:
            findings.append(Finding(number, line, hits))
    return tuple(findings)


def _hits(line: str, stopwords: frozenset[str]) -> tuple[str, ...]:
    """The stopwords in one line, after the exempt shapes are removed."""
    if TRAILER.match(line):
        return ()
    stripped = PATH_TOKEN.sub(" ", QUOTED_SPAN.sub(" ", CODE_SPAN.sub(" ", line)))
    folded = stripped.lower().translate(_FOLD)
    return tuple(word for word in _WORD.findall(folded) if word in stopwords)
