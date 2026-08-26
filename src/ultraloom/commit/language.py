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

# The tail of a span left open on an earlier line. CODE_SPAN and QUOTED_SPAN
# pair delimiters within one line, so a span that wraps across a line break is
# invisible to them and the quoted text is scored as prose -- a refusal earned
# by quoting the example correctly, which is how a gate teaches --no-verify.
#
# Whether a leftover delimiter opens or closes cannot be read off the line: it
# opens one when nothing is open, and closes one otherwise. So _spans carries
# a flag per delimiter through the message. Scoring stays per line -- each
# line keeps its own count, its own threshold decision and its own finding --
# and only the question "is a span open here" comes from above.
OPEN_SPAN = re.compile(r"`.*$")
QUOTED_SPAN = re.compile(r"\"[^\"]*\"")
# Only the double quote delimits. An apostrophe does not, so "don't" opens
# nothing -- which is why backticks and quotes need no different treatment.
OPEN_QUOTE = re.compile(r"\".*$")
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
    in_code = False
    in_quote = False

    for number, line in enumerate(text.splitlines(), start=1):
        if SCISSORS.match(line):
            # Everything below belongs to the diff, not to the message.
            break
        if line.startswith("#"):
            # git wrote this line and strips it again before the message is
            # stored, so a delimiter here belongs to no span the author wrote
            # and must not move the flags.
            continue
        scored, in_code, in_quote = _spans(line, in_code, in_quote)
        # After _spans and not before it: an exempted line is still the
        # author's text, and a span it opens goes on into the lines below.
        if any(pattern.search(line) for pattern in allow):
            continue
        hits = _hits(scored, stopwords, is_subject=number == 1)
        if len(hits) >= threshold:
            findings.append(Finding(number, line, hits))
    return tuple(findings)


def _spans(line: str, in_code: bool, in_quote: bool) -> tuple[str, bool, bool]:
    """One line with its quoted spans blanked, and the flags for the next line.

    Three cases per delimiter. A span open from above ends at the first
    delimiter on this line, or swallows the line whole if there is none. What
    is left is paired within the line as before. A delimiter still over after
    that pairing opens a span, so the rest of the line is quoted.
    """
    text = line
    if in_code:
        _, tick, rest = text.partition("`")
        if not tick:
            # No closing backtick anywhere: the line lies inside the span, and
            # a quote within it is code, so in_quote is left as it stands.
            return " ", True, in_quote
        text = " " + rest
    text = CODE_SPAN.sub(" ", text)
    in_code = "`" in text
    if in_code:
        text = OPEN_SPAN.sub(" ", text)

    # Quotes are read on what the code pass left, so a quote inside a code
    # span neither counts nor moves the quote flag.
    if in_quote:
        _, mark, rest = text.partition('"')
        if not mark:
            return " ", in_code, True
        text = " " + rest
    text = QUOTED_SPAN.sub(" ", text)
    in_quote = '"' in text
    if in_quote:
        text = OPEN_QUOTE.sub(" ", text)
    return text, in_code, in_quote


def _hits(line: str, stopwords: frozenset[str], *, is_subject: bool) -> tuple[str, ...]:
    """The stopwords in one line, after the exempt shapes are removed.

    Takes the line _spans has already blanked, so what arrives here is the
    author's own prose and nothing quoted.

    `is_subject` withholds the trailer exemption from line 1: no trailer block
    begins there, and the subject is the line the gate exists for.
    """
    if not is_subject and TRAILER.match(line):
        return ()
    stripped = NAME_PARTICLE.sub(" ", line)
    stripped = PATH_TOKEN.sub(" ", stripped)
    folded = stripped.lower().translate(_FOLD)
    return tuple(word for word in _WORD.findall(folded) if word in stopwords)
