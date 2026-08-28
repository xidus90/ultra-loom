// Package interview fills the gaps a tree cannot fill.
//
// It never prompts into the dark. init is called by agents as well as by
// people, and there stdin is closed -- a prompt nobody sees would hang the
// caller and look like the tool doing nothing. The same lesson as the
// invisible uv failure in space's run.sh.
package interview

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"

	"github.com/xidus90/ultra-loom/internal/answers"
)

var ErrNoTTY = errors.New("no terminal to ask on")

// migrationGlob is the one path a Django project regrets losing: a migration
// is history, and a rewritten one is a database nobody can reach any more.
const migrationGlob = "migrations/[0-9][0-9][0-9][0-9]_*.py"

type Question struct {
	Key     string
	Prompt  string
	Default string
	Flag    string
	apply   func(*answers.Answers, string) error
}

// Missing is the interview as data: what is still unanswered, in the order
// of the answer file, with the questions a stack brings after the ones every
// project gets.
func Missing(current answers.Answers) []Question {
	var open []Question
	if current.Project.CommitLanguage == "" {
		open = append(open, Question{
			Key: "commit_language", Prompt: "Language for commit messages",
			Default: "en", Flag: "--commit-language",
			apply: func(a *answers.Answers, v string) error {
				a.Project.CommitLanguage = v
				return nil
			},
		})
	}
	if current.Project.DocsLanguage == "" {
		open = append(open, Question{
			Key: "docs_language", Prompt: "Language for prose and documentation",
			Default: "de", Flag: "--docs-language",
			apply: func(a *answers.Answers, v string) error {
				a.Project.DocsLanguage = v
				return nil
			},
		})
	}
	if current.Gates.CoverageThreshold == 0 {
		open = append(open, Question{
			Key: "coverage_threshold", Prompt: "Coverage threshold in percent",
			Default: "100", Flag: "--coverage-threshold",
			apply: applyThreshold,
		})
	}
	if current.Gates.Wiki.Mode == "" {
		open = append(open, Question{
			Key: "wiki_mode", Prompt: fmt.Sprintf("Wiki mode %v", answers.WikiModes),
			Default: "none", Flag: "--wiki-mode",
			apply: applyWikiMode,
		})
	}
	// Nil, not empty: a question answered with no is an answer, and the
	// empty list it leaves must not read as a question never asked.
	if has(current.Project.Stacks, "django") && current.Policy.ProtectedPaths == nil {
		open = append(open, Question{
			Key: "protect_migrations", Prompt: "Protect Django migrations from being rewritten",
			Default: "yes", Flag: "--protect-migrations",
			apply: func(a *answers.Answers, v string) error {
				return applyChoice(v, &a.Policy.ProtectedPaths, migrationGlob)
			},
		})
	}
	if has(current.Project.Stacks, "python") && current.Policy.ForbiddenCommands == nil {
		// uv decides the default, not the question: where uv owns the
		// environment, pip install is the command that silently breaks it.
		fallback := "no"
		if has(current.Project.Stacks, "uv") {
			fallback = "yes"
		}
		open = append(open, Question{
			Key: "forbid_pip_install", Prompt: "Forbid pip install",
			Default: fallback, Flag: "--forbid-pip-install",
			apply: func(a *answers.Answers, v string) error {
				return applyChoice(v, &a.Policy.ForbiddenCommands, "pip install")
			},
		})
	}
	return open
}

func Run(in io.Reader, out io.Writer, interactive bool, current answers.Answers) (answers.Answers, error) {
	open := Missing(current)
	if len(open) == 0 {
		return current, nil
	}
	if !interactive {
		var flags []string
		for _, question := range open {
			flags = append(flags, question.Flag)
		}
		return answers.Answers{}, fmt.Errorf(
			"%w: unanswered, pass %s", ErrNoTTY, strings.Join(flags, " "))
	}
	reader := bufio.NewReader(in)
	for _, question := range open {
		if err := ask(reader, out, question, &current); err != nil {
			return answers.Answers{}, err
		}
	}
	return current, nil
}

// ask repeats one question until it is answered. The end of input is an
// answer of its own -- it means take the default -- but only while nothing
// wrong has been typed: after a rejected answer the same silence would be an
// endless question, so it ends the run instead.
func ask(reader *bufio.Reader, out io.Writer, question Question, current *answers.Answers) error {
	rejected := false
	for {
		fmt.Fprintf(out, "%s [%s]: ", question.Prompt, question.Default)
		line, err := reader.ReadString('\n')
		if err != nil && !errors.Is(err, io.EOF) {
			return fmt.Errorf("reading the answer to %s: %w", question.Key, err)
		}
		ended := errors.Is(err, io.EOF)
		given := strings.TrimSpace(line)
		if given == "" {
			if ended && rejected {
				return fmt.Errorf("%s: no usable answer before the end of input", question.Key)
			}
			given = question.Default
		}
		if applied := question.apply(current, given); applied != nil {
			fmt.Fprintf(out, "%v\n", applied)
			rejected = true
			continue
		}
		return nil
	}
}

func applyThreshold(a *answers.Answers, given string) error {
	percent, err := strconv.Atoi(given)
	if err != nil {
		return fmt.Errorf("%q is not a whole number", given)
	}
	if percent < 0 || percent > 100 {
		return fmt.Errorf("%d is not between 0 and 100", percent)
	}
	a.Gates.CoverageThreshold = percent
	return nil
}

func applyWikiMode(a *answers.Answers, given string) error {
	if !has(answers.WikiModes, given) {
		return fmt.Errorf("%q is none of %v", given, answers.WikiModes)
	}
	a.Gates.Wiki.Mode = given
	return nil
}

// applyChoice writes the entry a yes stands for, and an empty list for a no:
// the list, not its absence, is what says the question was asked.
func applyChoice(given string, list *[]string, entry string) error {
	switch strings.ToLower(given) {
	case "yes", "y":
		*list = []string{entry}
	case "no", "n":
		*list = []string{}
	default:
		return fmt.Errorf("answer yes or no, not %q", given)
	}
	return nil
}

func has(all []string, wanted string) bool {
	for _, one := range all {
		if one == wanted {
			return true
		}
	}
	return false
}
