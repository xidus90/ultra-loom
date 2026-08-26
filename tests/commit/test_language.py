"""What counts as obviously-the-wrong-language, line by line."""

from __future__ import annotations

import re

import pytest

from ultraloom.commit.language import scan


def test_an_english_message_is_clean() -> None:
    text = "Let the stop gate run one profile instead of the whole chain"
    assert scan(text, "en", 2) == ()


def test_german_prose_is_found() -> None:
    text = "Das Gate laeuft jetzt mit dem Profil und nicht mehr ueber die ganze Kette"
    found = scan(text, "en", 2)
    assert len(found) == 1
    assert found[0].line_number == 1
    assert len(found[0].hits) >= 2


def test_the_threshold_counts_per_line_not_per_message() -> None:
    """Two lines with one hit each are not one line with two.

    A body that lists two German page titles is exactly that shape, and it is
    the shape the threshold exists to let through.
    """
    text = "Add a page\n\nSee der Titel\nSee das Andere"
    assert scan(text, "en", 2) == ()


def test_one_hit_in_a_line_is_not_enough() -> None:
    text = "Rename the file to konzept-der-woche.md"
    assert scan(text, "en", 2) == ()


def test_a_quoted_sentence_does_not_count() -> None:
    """German turns up inside English messages; quoting is how."""
    text = 'The page says "der Bericht ist nicht vollstaendig" and it is right'
    assert scan(text, "en", 2) == ()


def test_a_code_span_does_not_count() -> None:
    text = "Rename `der_alte_name` to `the_new_name` and nicht more"
    assert scan(text, "en", 2) == ()


def test_a_path_does_not_count() -> None:
    text = "Move wiki/decisions/das-und-der-fall.md into the archive"
    assert scan(text, "en", 2) == ()


def test_a_trailer_does_not_count() -> None:
    text = "Fix the gate\n\nCo-Authored-By: Der Name <von@example.org>"
    assert scan(text, "en", 2) == ()


def test_a_name_particle_does_not_count() -> None:
    text = "The paper by von Neumann and von Braun describes the algorithm"
    assert scan(text, "en", 2) == ()


def test_von_without_a_capitalised_name_still_counts() -> None:
    text = "Das Ergebnis von dem Bericht und von der Pruefung"
    assert [f.line_number for f in scan(text, "en", 2)] == [1]


def test_the_diff_below_the_scissors_is_ignored() -> None:
    """`git commit --verbose` appends the whole diff, uncommented.

    Without the cut, every commit touching German prose would be refused.
    """
    text = (
        "Add the page\n"
        "# ------------------------ >8 ------------------------\n"
        "diff --git a/wiki/x.md b/wiki/x.md\n"
        "+der Bericht und das Ergebnis sind nicht vollstaendig\n"
    )
    assert scan(text, "en", 2) == ()


def test_comment_lines_are_ignored() -> None:
    """git writes its own hints into the file with a leading #."""
    text = "Add the page\n# Bitte gib eine Commit-Beschreibung fuer die Aenderungen ein\n"
    assert scan(text, "en", 2) == ()


def test_the_other_direction_finds_english_in_german() -> None:
    text = "The gate now runs with the profile and not with the whole chain"
    found = scan(text, "de", 2)
    assert len(found) == 1


def test_a_german_message_is_clean_under_de() -> None:
    text = "Das Gate laeuft jetzt mit dem Profil statt ueber die ganze Kette"
    assert scan(text, "de", 2) == ()


def test_an_allow_pattern_drops_the_whole_line() -> None:
    text = "Add the page\nQuelle: der Bericht und das Ergebnis"
    allow = (re.compile(r"^Quelle:"),)
    assert scan(text, "en", 2, allow) == ()


def test_a_finding_carries_the_line_and_its_hits() -> None:
    text = "Add a page\nDas Ergebnis und der Bericht fehlen"
    found = scan(text, "en", 2)
    assert found[0].line_number == 2
    assert "und" in found[0].hits


@pytest.mark.parametrize("word", ["die", "war", "man", "den", "hat", "in", "so", "an"])
def test_german_words_that_are_also_english_never_count(word: str) -> None:
    """"Let the process die in the war room" must not be a finding.

    Presence of a German word is evidence only when the word means nothing in
    the target language. A gate with false positives gets routed around with
    --no-verify and then protects nothing.
    """
    from ultraloom.commit.language import STOPWORDS

    assert word not in STOPWORDS["en"]


@pytest.mark.parametrize(
    "text",
    [
        "Für alles über allem",
        "Über die Katze, für sich genommen",
    ],
)
def test_umlauts_are_found_although_the_list_is_ascii(text: str) -> None:
    """A real German commit writes "fuer" with an umlaut; the list is ASCII.

    The texts here are chosen so that only the umlaut words can reach the
    threshold: strike the folding and this test goes red, which is the whole
    point of having it. An earlier version used a sentence whose plain-ASCII
    stopwords carried the count on their own, and passed without the folding.
    """
    assert [f.line_number for f in scan(text, "en", 2)] == [1]


def test_a_hyphenated_trailer_does_not_count() -> None:
    text = "Fix the gate\n\nSigned-off-by: Der Name und der Andere"
    assert scan(text, "en", 2) == ()


def test_a_listed_unhyphenated_trailer_does_not_count() -> None:
    for key in ("Fixes", "Closes", "Refs", "Ref", "Cc", "Link", "Bug", "BREAKING CHANGE"):
        text = f"Fix the gate\n\n{key}: das und der Bericht"
        assert scan(text, "en", 2) == (), key


def test_a_conventional_commit_subject_is_not_a_trailer() -> None:
    """The subject is the line that matters, and for a one-line commit it is all there is."""
    for subject in ("fix: ", "Fix: ", "docs: ", "chore: ", "Note: "):
        text = f"{subject}behebt den Fehler und das Problem"
        assert [f.line_number for f in scan(text, "en", 2)] == [1], subject


def test_an_english_fest_is_not_a_finding() -> None:
    text = "Add the fest and the beer fest to the calendar"
    assert scan(text, "en", 2) == ()


def test_no_trailer_is_exempt_on_the_first_line() -> None:
    """A trailer block never legitimately begins on line 1, so the subject is prose."""
    for key in ("Ref", "Fixes", "Co-Authored-By", "Auto-merge", "Feature-flag", "BREAKING CHANGE"):
        text = f"{key}: behebt den Fehler und das Problem"
        assert [f.line_number for f in scan(text, "en", 2)] == [1], key


def test_a_breaking_change_footer_does_not_count() -> None:
    """The space defeats the hyphenated shape, but it is a real footer."""
    text = "Change the gate\n\nBREAKING CHANGE: das Verhalten und der Vertrag aendern sich"
    assert scan(text, "en", 2) == ()


def test_a_german_still_is_not_a_finding() -> None:
    """`still` is ordinary German -- quiet -- and reaches the threshold on one word twice."""
    text = "Lasse den Prozess still laufen und still beenden"
    assert scan(text, "de", 2) == ()


def test_the_opening_line_of_a_wrapped_span_is_exempt() -> None:
    """CODE_SPAN works per line, so a span that wraps never sees its closing backtick.

    This is the shape a careful author writes: the foreign example is quoted,
    and the line break falls inside the quotes. Refusing it is the failure the
    spec calls fatal.
    """
    text = (
        "Widen the gate\n\n"
        "real trailer key and a perfectly good subject: `Ref: behebt den Fehler und das\n"
        "Problem` and any capitalised hyphenated first word"
    )
    assert scan(text, "en", 2) == ()


def test_a_closing_backtick_with_no_opener_leaves_its_text_scored() -> None:
    """The record of the case that used to be the gap, in the form it now takes.

    A leftover backtick can close a span as well as open one. Which it is now
    comes from the span flag, and here no line before this one opened
    anything, so the backtick pairs with nothing and the text ahead of it is
    prose like any other.
    """
    text = "Widen the gate\n\nund der Bericht` shows what the gate printed"
    assert [f.line_number for f in scan(text, "en", 2)] == [3]


def test_a_balanced_span_is_left_alone() -> None:
    """The rule must not reach back into a line whose backticks all pair up."""
    assert scan("Report `das und der` in the output", "en", 2) == ()
    # Prose after a balanced span is still prose, and still counted.
    assert [f.line_number for f in scan("Report `x` und der Bericht das", "en", 2)] == [1]


def test_a_lone_trailing_backtick_strips_nothing() -> None:
    """Nothing follows the backtick, so the line is scored exactly as it reads."""
    assert [f.line_number for f in scan("Der Bericht und das Ergebnis `", "en", 2)] == [1]


def test_the_tail_of_a_wrapped_code_span_is_exempt() -> None:
    """The half the per-line rule could not reach: quoted text before the backtick."""
    text = (
        "Widen the gate\n\n"
        "The subject was `Ref: behebt den Fehler\n"
        "und das Problem` and the gate said nothing"
    )
    assert scan(text, "en", 2) == ()


def test_a_code_span_wrapping_three_lines_is_exempt() -> None:
    """The middle line lies wholly inside the span and carries no backtick at all."""
    text = (
        "Widen the gate\n\n"
        "The subject was `Ref: behebt den Fehler\n"
        "und das Problem und der Bericht\n"
        "und die Pruefung` and the gate said nothing"
    )
    assert scan(text, "en", 2) == ()


def test_a_quoted_span_does_not_wrap_across_lines() -> None:
    """Reworked from three tests that asserted the opposite, and kept as the record.

    Backtick wrapping is observed in real commit messages; quote wrapping was
    only ever constructed here. An unpaired quote is a measurement or a stray
    far more often than half a citation, so both halves are scored as prose.
    """
    text = (
        "Widen the gate\n\n"
        'He said "es behebt den Fehler und das\n'
        'Problem und der Bericht" and left'
    )
    assert [f.line_number for f in scan(text, "en", 2)] == [3, 4]


def test_a_quoted_span_within_one_line_is_still_exempt() -> None:
    """Only the wrapping went away; pairing within the line is untouched."""
    assert scan('He said "das und der" and left', "en", 2) == ()


def test_a_lone_quote_is_punctuation_not_a_span_opener() -> None:
    """A measurement, and the rest of the line is ordinary prose."""
    text = 'Set the width to 80" und der Bericht das'
    assert [f.line_number for f in scan(text, "en", 2)] == [1]


def test_an_apostrophe_is_not_a_quote_delimiter() -> None:
    """Only the double quote delimits; `don't` must not open anything."""
    assert [f.line_number for f in scan("The gate don't und der Bericht das care", "en", 2)] == [1]


def test_a_git_hint_line_does_not_move_the_span_flags() -> None:
    """git wrote the `#` lines and strips them again, so their delimiters are not the author's.

    Both directions matter: a stray backtick in a hint must not blank the
    prose below it, and a span the author opened must survive a hint line
    sitting inside it.
    """
    noise = (
        "Widen the gate\n\n"
        "# On branch feat/x -- use `git add` to stage\n"
        "# Changes not staged for commit: `\n"
        "Der Bericht und das Ergebnis fehlen"
    )
    assert [f.line_number for f in scan(noise, "en", 2)] == [5]

    spanning = (
        "Widen the gate\n\n"
        "He wrote `Ref: behebt den Fehler\n"
        "# a git hint with a stray ` backtick\n"
        "und das Problem` and stopped"
    )
    assert scan(spanning, "en", 2) == ()


def test_an_exempted_line_still_carries_its_span_onward() -> None:
    """An allowed line is the author's text too, so a span it opens goes on below."""
    allow = (re.compile("^WIP"),)
    text = (
        "Widen the gate\n\n"
        "WIP `Ref: behebt den Fehler\n"
        "und das Problem` and stopped"
    )
    assert scan(text, "en", 2, allow) == ()


def test_an_unpaired_quote_does_not_outlive_its_paragraph() -> None:
    """A measurement in the subject must not switch the gate off for the message.

    `80" wide` is how people write measurements, not an exotic input. Before
    the blank-line rule the quote it opens ran to the end of the message and
    two lines of plain German walked through in silence -- the gate disabling
    itself, which is the fault this whole feature argues against.
    """
    text = (
        'Add a 80" wide banner\n'
        "\n"
        "Das Ergebnis und der Bericht fehlen\n"
        "Das Verhalten und der Vertrag aendern sich"
    )
    findings = scan(text, "en", 2)
    assert [finding.line_number for finding in findings] == [3, 4]


def test_an_unpaired_backtick_does_not_outlive_its_paragraph() -> None:
    text = (
        "Add a 80` wide banner\n"
        "\n"
        "Das Ergebnis und der Bericht fehlen\n"
        "Das Verhalten und der Vertrag aendern sich"
    )
    findings = scan(text, "en", 2)
    assert [finding.line_number for finding in findings] == [3, 4]


def test_a_span_wrapped_inside_one_paragraph_is_still_exempt() -> None:
    """The bound is the paragraph, so a span that stays inside one is untouched."""
    code = (
        "Widen the gate\n\n"
        "He wrote `Ref: behebt den Fehler\n"
        "und das Problem` and stopped"
    )
    assert scan(code, "en", 2) == ()
    # No quoted twin: a quoted span does not wrap, so there is nothing for
    # the paragraph bound to bound. See test_a_quoted_span_does_not_wrap.


def test_a_span_does_not_wrap_across_a_blank_line() -> None:
    """A paragraph break is not a plausible span interior, so the span ends there."""
    code = (
        "Widen the gate\n\n"
        "He wrote `Ref: behebt den Fehler\n"
        "\n"
        "und das Problem` and stopped"
    )
    assert [finding.line_number for finding in scan(code, "en", 2)] == [5]
    quoted = (
        "Widen the gate\n\n"
        'He said "es behebt den Fehler\n'
        "\n"
        'und das Problem" and stopped'
    )
    assert [finding.line_number for finding in scan(quoted, "en", 2)] == [5]


def test_a_path_and_a_name_particle_inside_a_wrapped_span() -> None:
    """Cheap insurance on the order of the strips: span blanking runs first now."""
    text = (
        "Widen the gate\n\n"
        "He wrote `siehe docs/das/und.md von Neumann und das\n"
        "Problem und der Bericht` and stopped"
    )
    assert scan(text, "en", 2) == ()


def test_a_path_and_a_name_particle_outside_a_span() -> None:
    """Both shapes are still removed where no span is involved, and prose still counts."""
    assert scan("Report docs/das/und.md by von Neumann to the team", "en", 2) == ()
    text = "Report docs/das/und.md by von Neumann und der Bericht das"
    assert [f.line_number for f in scan(text, "en", 2)] == [1]


def test_a_stray_quote_mid_paragraph_does_not_disable_the_gate() -> None:
    """The blank-line reset fires before the delimiter, not after it.

    A body paragraph is normally the whole body, so a stray quote inside one
    had nothing left to bound it and the gate stopped checking.
    """
    text = (
        "Fix the parser\n"
        "\n"
        'The input may contain a " character\n'
        "Das Ergebnis und der Bericht fehlen\n"
        "Das Verhalten und der Vertrag aendern sich"
    )
    assert [f.line_number for f in scan(text, "en", 2)] == [4, 5]


def test_a_stray_quote_with_no_blank_line_anywhere_does_not_disable_the_gate() -> None:
    """A two-line message has no paragraph break, so the reset never fires at all."""
    text = 'Add a 80" wide banner\nDas Ergebnis und der Bericht fehlen'
    assert [f.line_number for f in scan(text, "en", 2)] == [2]


def test_a_removed_span_leaves_a_separator_behind() -> None:
    """The replacement is a space, never the empty string.

    An empty replacement welds the halves of a line together: `un` + `d der`
    becomes `und der` and manufactures a stopword nobody wrote. Scored with a
    space there is one hit, which is under the threshold; welded there are two.
    """
    assert scan("Fix un`x`d der parser", "en", 2) == ()


def test_the_tail_of_a_carried_span_cannot_pass_as_a_trailer() -> None:
    """The space in front of the tail is load-bearing too, by a different mechanism.

    Not word splitting: a leading space cannot change which words a line
    yields. It is TRAILER's `^` anchor. Without the space the remainder after
    the closing backtick starts the line, so a tail that happens to open with
    a trailer key matches TRAILER and takes the whole line out of scoring.
    """
    text = (
        "Widen the gate\n\n"
        "He wrote `something\n"
        "x`Ref: das und der Bericht"
    )
    assert [f.line_number for f in scan(text, "en", 2)] == [4]


def test_a_stray_backtick_in_the_subject_does_not_silence_the_body() -> None:
    """A span never spans out of the subject, for the reason TRAILER is withheld there.

    The two-line message is the shape where nothing else bounds it: there is
    no blank line for the paragraph rule to fire on.
    """
    text = "Add a 80` wide banner\nDas Ergebnis und der Bericht fehlen"
    assert [f.line_number for f in scan(text, "en", 2)] == [2]


def test_a_span_opened_in_the_body_still_closes_two_lines_later() -> None:
    """The other direction: the line-1 rule must not reach into body wrapping."""
    text = (
        "Widen the gate\n\n"
        "He wrote `Ref: behebt den Fehler\n"
        "und das Problem und der Bericht\n"
        "und die Pruefung` and stopped"
    )
    assert scan(text, "en", 2) == ()
