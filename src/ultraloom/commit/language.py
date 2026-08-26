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
# war, man, den, hat, in, so, an, fest. "Let the process die in the war room"
# must not be a finding, and neither must "Add the beer fest to the calendar".
#
# The rule binds in both directions, and the English list is where it is easier
# to forget: deliberately absent from it, each a normal German word, are still,
# was, will, fast, bald, hier, rate, boot and eben.
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
            "ihn",
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
            "rather", "already", "every", "each", "again",
        }
    ),
}

# `git commit --verbose` appends the whole diff below this marker, uncommented.
# The diff carries whatever the change touched, so scoring it would refuse
# every commit that goes near prose in the other language.
SCISSORS = re.compile(r"^#\s*-+\s*>8\s*-+")

# Shapes that carry the other language inside an otherwise fine message. All
# five are removed from a line before it is scored, because a gate with false
# positives gets routed around with --no-verify and then protects nothing.
# Only a real git trailer, never a conventional-commit subject. What separates
# a trailer is the capitalised hyphenated shape -- Co-Authored-By,
# Signed-off-by -- plus the handful of unhyphenated ones git tooling and the
# conventional-commit footer actually write.
#
# The pattern alone is not enough, because the shape is not exclusive: `Ref:`
# and any capitalised hyphenated first word, `Auto-merge:`, are perfectly good
# subjects too. So the exemption is refused on line 1 outright -- a trailer
# block never legitimately begins there -- which closes both holes at once and
# costs nothing real. See _hits.
TRAILER = re.compile(
    r"^(?:[A-Z][A-Za-z]*(?:-[A-Za-z]+)+"
    r"|Fixes|Closes|Refs|Ref|Cc|Link|Bug|BREAKING CHANGE):\s"
)
CODE_SPAN = re.compile(r"`[^`]*`")

# A code span that wraps across a line break. CODE_SPAN pairs backticks
# within one line, so the opening half of a wrapped span never sees a closing
# backtick and the quoted text is scored as prose -- a refusal earned by
# quoting the example correctly, which is how a gate teaches --no-verify.
#
# Applied after CODE_SPAN, a backtick left over can only be one that opens a
# span, so the rest of the line is quoted text. Per-line scoring stays
# intact: the threshold rule depends on lines being independent, and this
# needs nothing from the line before.
#
# The closing half is not covered, and cannot be without that state: there
# the quoted text lies *before* the leftover backtick, and nothing on the
# line says which of the two it is. See
# test_the_tail_of_a_wrapped_span_is_still_scored.
OPEN_SPAN = re.compile(r"`.*$")
QUOTED_SPAN = re.compile(r"\"[^\"]*\"")
PATH_TOKEN = re.compile(r"\S*(?:[/\\]\S*|\.[A-Za-z0-9]{1,5})(?=\s|$)")

# A name particle, not a function word: "von Neumann", "van Gogh",
# "de Broglie". The lowercase particle followed by a capitalised word is the
# shape, and German prose almost never has it -- there the particle is
# followed by an article or a lowercase noun. Without this, a paper citing
# two such names reaches the threshold on its own.
NAME_PARTICLE = re.compile(r"\b(?:von|van|de|du|della|di)\s+[A-Z]\w+")

# Words may carry umlauts even where the stopword list spells them out: a
# real German commit writes the ASCII-transcribed form or the native one
# with an umlaut, and both must be found. The list is ASCII, so the text is
# folded to match it -- see _FOLD.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# The stopword lists are ASCII because this file is. German text is not: it
# uses the native umlaut spellings. Folding the text rather than doubling
# every entry keeps one list instead of two that can drift.
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
        hits = _hits(line, stopwords, is_subject=number == 1)
        if len(hits) >= threshold:
            findings.append(Finding(number, line, hits))
    return tuple(findings)


def _hits(line: str, stopwords: frozenset[str], *, is_subject: bool) -> tuple[str, ...]:
    """The stopwords in one line, after the exempt shapes are removed.

    `is_subject` withholds the trailer exemption from line 1: no trailer block
    begins there, and the subject is the line the gate exists for.
    """
    if not is_subject and TRAILER.match(line):
        return ()
    stripped = NAME_PARTICLE.sub(" ", line)
    stripped = CODE_SPAN.sub(" ", stripped)
    stripped = OPEN_SPAN.sub(" ", stripped)
    stripped = QUOTED_SPAN.sub(" ", stripped)
    stripped = PATH_TOKEN.sub(" ", stripped)
    folded = stripped.lower().translate(_FOLD)
    return tuple(word for word in _WORD.findall(folded) if word in stopwords)
