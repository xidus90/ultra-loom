"""The decision itself: one text against one word list.

No files, no configuration. Whoever wants to understand what counts as a
finding reads this module and nothing else.
"""

from __future__ import annotations

import re
import unicodedata
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
# Strictly per line, and deliberately unlike CODE_SPAN. A quoted span does not
# wrap: an unpaired `"` in prose is a measurement or a stray, as in `80" wide`,
# far more often than the opening half of a citation. Treating it as a span
# opener let one stray quote blank the rest of its line and, while the flag
# carried, everything below -- exit 0 on a message of plain German. Backtick
# wrapping is observed in real commit messages and pays for its carry; quote
# wrapping was only ever constructed in this suite, so it does not.
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

# A run of foreign script is worth one hit, and the hit string is the run
# itself. Cut here so a message quoting a whole paragraph does not print that
# paragraph back in the refusal; nothing else depends on the length.
_RUN_LIMIT = 12


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
    """Every line whose hit count reaches the threshold.

    Per line and not per message: a body listing two page titles in the other
    language is two lines of one hit, not one line of two, and the second
    reading would refuse it.
    """
    stopwords = STOPWORDS[language]
    findings: list[Finding] = []
    in_code = False

    for number, line in enumerate(text.splitlines(), start=1):
        if SCISSORS.match(line):
            # Everything below belongs to the diff, not to the message.
            break
        if line.startswith("#"):
            # git wrote this line and strips it again before the message is
            # stored, so a delimiter here belongs to no span the author wrote
            # and must not move the flags.
            continue
        if not line.strip():
            # A span closes at a paragraph break. Nothing else bounds one, and
            # unbounded is not a small fault: a lone `"` in `80" wide` -- a
            # measurement, not an exotic input -- would otherwise open a span
            # that runs to the end of the message and lets every German line
            # below it through in silence. A gate that switches itself off is
            # worse than one that refuses too much, and a paragraph break is
            # not a plausible span interior.
            in_code = False
            continue
        scored, in_code = _spans(line, in_code)
        if number == 1:
            # A span does not span out of the subject, for the reason TRAILER
            # is withheld there: neither shape begins in a subject line. This
            # is what bounds the two-line message, where no blank line follows
            # to close a stray backtick and the whole body would go quiet.
            in_code = False
        # After _spans and not before it: an exempted line is still the
        # author's text, and a span it opens goes on into the lines below.
        if any(pattern.search(line) for pattern in allow):
            continue
        hits = _hits(scored, stopwords, is_subject=number == 1)
        if len(hits) >= threshold:
            findings.append(Finding(number, line, hits))
    return tuple(findings)


def _spans(line: str, in_code: bool) -> tuple[str, bool]:
    """One line with its quoted spans blanked, and the code flag for the next.

    A code span open from above ends at the first backtick on this line, or
    swallows the line whole if there is none. What is left is paired within
    the line, and a backtick still over after that pairing opens a span, so
    the rest of the line is quoted.

    Quoted spans get none of that: they are paired within the line and
    nothing else -- see QUOTED_SPAN for why the two differ.

    Every substitution puts a space in place of what it removes. An empty
    replacement would weld the halves together, turning `un``x``d der` into
    `und der` and manufacturing a stopword that was never written.
    """
    text = line
    if in_code:
        _, tick, rest = text.partition("`")
        if not tick:
            # No closing backtick anywhere: the line lies inside the span.
            return " ", True
        # The space is not cosmetic, and not about word splitting either: it
        # is TRAILER's `^`. Without it the tail starts the line, so a tail
        # opening with a trailer key would take the line out of scoring.
        text = " " + rest
    text = CODE_SPAN.sub(" ", text)
    in_code = "`" in text
    if in_code:
        text = OPEN_SPAN.sub(" ", text)

    # Read on what the code pass left, so a quote inside a code span is code.
    return QUOTED_SPAN.sub(" ", text), in_code


def _hits(line: str, stopwords: frozenset[str], *, is_subject: bool) -> tuple[str, ...]:
    """The hits in one line, after the exempt shapes are removed.

    A hit is a stopword of the other language or a run of letters in a
    non-Latin script; the two weigh the same, so the threshold, the
    per-line counting and every exemption read one kind of evidence.

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
    words = tuple(word for word in _WORD.findall(folded) if word in stopwords)
    # Scored on what _spans and the strippers above left, so a foreign
    # script inside a code span, a path or a trailer is exempt by the same
    # machinery that exempts a stopword there.
    return words + _script_runs(stripped)


def _script(char: str) -> str:
    """The script of one letter, empty for Latin and for anything not a letter.

    Read off `unicodedata.name()` rather than codepoint ranges: the name
    begins with the script -- CYRILLIC, DEVANAGARI, THAI -- so one lookup
    covers every script at once, where ranges would be a table per script that
    has to be kept correct against each Unicode revision. The lookup is C and
    runs once per character of a commit message, which is not a size where the
    difference is measurable.
    """
    if not unicodedata.category(char).startswith("L"):
        return ""
    script, _, _ = unicodedata.name(char, "").partition(" ")
    return "" if script == "LATIN" else script


def _script_runs(line: str) -> tuple[str, ...]:
    """One entry per run of letters in a single non-Latin script.

    Per run and never per character: a Chinese word is a handful of characters
    and would clear any usable threshold on its own, so the gate would refuse
    every message that names one. A run is a word, and a word is one hit --
    the same weight a stopword carries, which is why everything already built
    around stopword hits applies to these unchanged.
    """
    runs: list[str] = []
    current: list[str] = []
    script = ""

    for char in line:
        if current and unicodedata.category(char).startswith("M"):
            # A combining mark spells the letter in front of it. Dropping it
            # out of the run would split Devanagari and Thai words into one
            # run per consonant and multiply their weight.
            current.append(char)
            continue
        found = _script(char)
        if found and found == script:
            current.append(char)
            continue
        if current:
            runs.append("".join(current))
        current = [char] if found else []
        script = found
    if current:
        runs.append("".join(current))

    return tuple(run[:_RUN_LIMIT] for run in runs)
