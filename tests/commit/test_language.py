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
    assert scan(text, "en", 2) != ()


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
    assert scan(text, "en", 2) != ()


def test_a_hyphenated_trailer_does_not_count() -> None:
    text = "Fix the gate\n\nSigned-off-by: Der Name und der Andere"
    assert scan(text, "en", 2) == ()


def test_a_listed_unhyphenated_trailer_does_not_count() -> None:
    for key in ("Fixes", "Closes", "Refs", "Ref", "Cc", "Link", "Bug"):
        text = f"{key}: das und der Bericht"
        assert scan(text, "en", 2) == (), key


def test_a_conventional_commit_subject_is_not_a_trailer() -> None:
    """The subject is the line that matters, and for a one-line commit it is all there is."""
    for subject in ("fix: ", "Fix: ", "docs: ", "chore: ", "Note: "):
        text = f"{subject}behebt den Fehler und das Problem"
        assert scan(text, "en", 2) != (), subject


def test_an_english_fest_is_not_a_finding() -> None:
    text = "Add the fest and the beer fest to the calendar"
    assert scan(text, "en", 2) == ()


def test_a_german_still_is_not_a_finding() -> None:
    """`still` is ordinary German -- quiet -- and reaches the threshold on one word twice."""
    text = "Lasse den Prozess still laufen und still beenden"
    assert scan(text, "de", 2) == ()
