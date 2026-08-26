# ultraloom

[Deutsch](README.de.md)

A check chain that puts one interface in front of ruff, eslint, gdlint, mypy,
tsc, pytest, vitest and coverage — and an optional graph harness for agent
flows.

## The check chain

    uvx ultraloom check lint
    uvx ultraloom check types
    uvx ultraloom check test
    uvx ultraloom check coverage
    uvx ultraloom check all

No installation in your project, no LLM dependency, no API key. The tool for
each check comes from a language preset; the place it runs comes from your
project's `.ultraloom/config.toml`.

`--threshold` sets the number ultraloom *reports* beside the coverage check.
ultraloom does not enforce it — your coverage tool's own configuration decides
whether the run passes. A line reading "ok" for a threshold nobody checked is
the one failure in this system that actually does damage. Concretely, for
Python: `coverage report` takes its exit code from `fail_under` and from
nothing else, so without that key in the project's own configuration a run at
83% is green. The same holds for `[verify.coverage].report` — naming a report
command does not make anybody enforce a number.

In Python, `check coverage` measures before it reports: `coverage report` only
reads a file that some earlier run has to have written. Who does that measuring
follows from the set of checks you asked for, not from the table alone — see
*Order between checks* below. In `check all` the suite runs **once**: `test`
runs under `coverage run`, and `coverage report` reads what it wrote, in the
stage after it.

A check is resolved in this order, and ultraloom never guesses beyond it:

1. `[verify].<kind>` in `.ultraloom/config.toml`
2. `.ultraloom/checks/<kind>.*` — a script you wrote. A `.py` file is run with
   ultraloom's own interpreter, anything else directly. With more than one
   match the first by name wins, so keep one script per check.
3. the preset for the language ultraloom detects from a marker file
   (`pyproject.toml`, `package.json`, `project.godot`)

A check that cannot be resolved is reported as a failure, never skipped.

The presets ask their tools for their terse modes, because a check report is
read by a repairing agent that pays for every token of it on every round. One
consequence is worth knowing in advance: `mypy --no-error-summary` drops the
"Success: no issues found" line too, so a green `types` check writes nothing at
all. The verdict rides on the exit code, as it always has — but an empty report
is not a check that did not run. GDScript has no coverage preset for the same
family of reasons: the tools that measure it are an editor addon and a
project-owned script, neither of which is a command another project could run,
and inventing one would look like a check without being one. Such a project
names its own under `[verify.coverage]`.

## Configuration

`.ultraloom/config.toml`, all of it optional:

```toml
[verify]
lint = "ruff check ."                 # a string: one command, as before
types = ["mypy src", "pyright"]       # a list: several, one after the other
test = "pytest -q"
max_parallel = 4                      # default: os.process_cpu_count()

[verify.lint]                         # a table: several, with switches
commands = ["gdlint .", "gdformat --check ."]
threaded = true

[verify.after]                        # order between checks
coverage = "test"

[verify.coverage]
threshold = 100
report = "coverage.xml"

[exec]
# Put in front of every check command, for a project that builds in a container.
prefix = "docker compose exec -T web"

[agent]
# MCP servers an agent node with the "mcp" tool profile may reach.
mcp_servers = ["wiki"]
# Which settings a repair run loads. The three reserved words are Claude Code's
# own; anything else is a path to one file, relative to --root.
settings = ["project"]
# Where the Claude CLI is, when the SDK's own search does not find it.
cli_path = "C:/Users/me/AppData/Local/Programs/claude/claude.exe"
```

`[agent].cli_path` is for the machine whose only Claude CLI is something the
SDK refuses to start -- an npm shim named `claude.CMD`, say. Without it every
agent node dies a few seconds in, on a message naming an option ultraloom did
not offer. `ULTRALOOM_CLI_PATH` says the same thing and **beats** the file:
whoever exports it does so because the project's file is wrong for this
machine, and the other way round the variable would be dead everywhere as soon
as one project wrote the key down. A blank value on either side counts as
unset, which is how a machine that exports the variable switches it off again.
A path that is not a file is refused when the configuration is read -- before
the first node, rather than once per agent call.

The same holds when nothing is configured at all: a `run` whose flow has an
agent node looks for a startable CLI once, before the run exists, and says
which of the three ways out to take if there is none. A flow of code nodes and
a run started with `--no-model` never ask the question.

`[agent].settings` says which settings a run inherits. The default is
`["project"]` -- the target project's own `.claude/settings.json`, and nothing
else. That is the one source that travels into a git worktree, because it is
the one that is versioned; `.claude/settings.local.json` is untracked and stays
behind, and `~/.claude/settings.json` belongs to the machine rather than to the
project. Measured against a repair run, the difference is not only tidiness:
dropping the user's settings cut the first round's prompt from 14 381 to 4 901
tokens, because the plugins and skills configured there stop loading.

`"user"`, `"project"` and `"local"` are reserved words. Anything else is a path
relative to `--root`, loaded on top of them:

```toml
[agent]
settings = []                                # no inherited settings at all
settings = ["hooks/repair.json"]             # one named file, and only it
settings = ["project", "../.claude/settings.json"]
```

At most one path: `--settings` takes one, and merging several would mean
rebuilding Claude Code's own merge semantics here. The order inside the list
means nothing -- the precedence is Claude Code's and runs managed settings,
`--settings`, `.claude/settings.local.json`, `.claude/settings.json`,
`~/.claude/settings.json`, highest first. A named path therefore outranks both
project files on any scalar key; hooks add up, scalars do not.

A path that is not a file is refused when the configuration is read, which is
also what catches a misspelled word: `"porject"` is a path, and the message
names the three that are not. `"managed"` is refused by name, because managed
settings always apply and nothing here overrides them.

`[agent].settings` covers settings files and nothing else. The MCP servers a
machine configures in `~/.claude.json` arrive by a different route and are
unaffected -- they cost no tokens either, because the `tools` cap keeps them
out of the prompt: the adapter names the built-in tools exhaustively, and what
it does not name never reaches the model. `[agent].mcp_servers` keeps nothing
out; it is an allow-list that only ever widens `allowed_tools`.

Which wheel of `claude-agent-sdk` gets installed decides whether the agent
path runs at all, so the extra pins one exact version. The wheels for a
specific platform carry a `claude` executable; the platform-independent one
does not, and 0.2.144 shipped no Windows wheel -- so on Windows that release
leaves the SDK with nothing to start. A lower bound would not have helped: the
*newer* release was the broken one.

`lint`, `types` and `test` take three shapes, told apart by type: a string is
one command, a list is several, and a table is the full form with `commands`
(required, not empty) and `threaded` (default `false`). A string and a table
under the same name is something TOML cannot express, so the parser refuses it
before ultraloom sees it.

`coverage` takes **none** of the three, and says so in every shape: a string or
a list under `[verify]` is refused with "[coverage] must be a table" (the
message names the leaf, not the full heading),
and a `[verify.coverage]` carrying `commands` or `threaded` is refused by name
with a pointer at `report`. That is where the command belongs. What is *not*
caught is a typo inside `[verify.coverage]` — a key that is neither `report`
nor `threshold` is ignored without a word, so `reprot = "…"` leaves the check
on its script or its preset.

Every command of a kind runs, including the ones after the first red one: the
repairer is owed the whole list of findings, and half a list costs another paid
round through the model. `threaded = true` runs them at the same time, and is
therefore a pure speed switch — the verdict is the same either way. The timeout
applies per command, so a linter's deadline does not depend on how many
siblings it has. An empty `commands`, or a blank command in it, is an error:
what would run is the `[exec].prefix` alone, and a prefix that exits 0 reports
a check nobody configured as passed.

`max_parallel` caps the check *processes* running at once over the whole run —
stages, kinds and commands share one counter, and reader threads do not count
against it. Without that cap `threaded = true` is a foot-gun: four Godot
processes at once is not four times the speed.

### Order between checks

Checks run in **stages**: concurrently inside a stage, one stage after the
other. The edges come from the language preset; `[verify.after]` overrides
them and maps a kind onto the single kind it reads from.

| language | stage 0 | stage 1 |
| --- | --- | --- |
| Python | lint, types, test | coverage |
| Node | lint, types, test, coverage | — |
| GDScript | lint, test | (none) |

Node stays single-stage because `vitest run --coverage` measures and reports in
one run. The table shows what the *presets* answer for a run that asks for
every kind; a project that configures a kind itself gets its own command, and a
stage only exists for the kinds actually requested.

The GDScript row is short because two presets are missing, and neither is an
oversight in this table. There is no `types` preset — GDScript has no type
checker to name, so `check types` in a Godot project falls through to a red
"GDScript has no types tool — a known limitation, not a passed check" — unless
the project names a command of its own under `[verify].types` or puts a script
at `.ultraloom/checks/types.*`, both of which are found first. And
there is no `coverage` preset — the tools that measure GDScript coverage are an
editor addon and a project-owned script, neither of which is a command another
project could run. There is therefore no second stage at all until the project
makes one: a Godot project that measures coverage names its report command under
`[verify.coverage].report` **and** its order under `[verify.after]` —
`coverage = "test"` — itself. Both gaps are gaps in the presets, not in this
page.

A kind that was not requested drops out of the stages without holding the rest
up: `check coverage` on its own runs immediately rather than after an empty
stage 0. A cycle in the edges is refused with the path it found, not walked
into.

**Who measures, in one sentence:** if the check I wait for runs in this same
pass and can measure as a by-product, it measures — otherwise I measure myself.

| requested | `test` runs as | `coverage` runs as | suite runs |
| --- | --- | --- | --- |
| test + coverage | `coverage run -m pytest` | `coverage report`, the stage after | 1 |
| test only | `pytest` | — | 1, with no measuring overhead |
| coverage only | — | measure, then report | 1 |
| `check all` | `coverage run -m pytest` | `coverage report`, the stage after | 1 |

A project that configures `test` itself has no measuring variant ultraloom
knows about, so `coverage` falls back to measuring for itself. ultraloom does
not guess whether somebody else's test command measures.

### Why a check is red

Besides a tool that simply found something, a red result carries a source:

| source | meaning |
| --- | --- |
| `unavailable` | the check could not be resolved at all — no config, no script, no preset. Red, never skipped. |
| `unready` | it resolved, but the project is not ready for it (a Godot project that was never imported). |
| `blocked` | it did not run, because the check it waits for was red. |

`blocked` is red like the others and is not skipped — but it is not out of
reach either: it closes itself the moment its predecessor is green. It is
therefore not something a repairer should touch, and `verify-until-green`
leaves it out of the decision to give up.

### Before you configure a check

**A check command that comes from a hook script has to be looked at.** ultraloom
reads the exit code and nothing else. Hook scripts routinely report their
findings on stdout and exit 0 on purpose — a Claude Code `Stop` hook that
exited 2 would refuse the agent its end of turn. Entered directly as a check
command, such a script reads as a passed check whatever it found, and ultraloom
cannot tell. Put a thin shell in front of it that calls the same findings and
only changes the channel.

**A command that leaves a long-lived grandchild behind is red**, even when it
exited 0, and it costs five seconds on top. ultraloom collects a command's
output on reader threads; a daemon or server the command started keeps the pipe
open, the readers cannot be joined, and they are given up on after a grace
period. What came back is then a prefix — and a threshold or a failure count
may be in the part that did not. A check whose output nobody could read in full
is not a passed check. The report says so in its own words.

## Policy

    ultraloom policy check <kind> <value>   # by hand, or from a script
    ultraloom policy hook                   # reads Claude Code's payload from stdin

Rules about what an agent must not touch usually live as prose in a CLAUDE.md
or as a hand-written hook script in one repository. Prose enforces nothing, and
a script per repo drifts. The policy answers the second question of the same
family the check chain answers: not *is this project green*, but *may this tool
call happen at all* — with the same tool everywhere, and with a reason the agent
gets to read.

It refuses on three kinds of subject: the **path** a file tool writes to, the
**command** line `Bash` would run, and the **content** a file tool would put on
disk. Tool names themselves are deliberately not a kind — Claude Code's own
`permissions` do that, and a second place with the same job is a source of
contradictions.

### The rules

Every kind gets its own section in `.ultraloom/config.toml`, and every section
its own mode:

```toml
[policy.paths]
mode = "deny"        # "allow" turns it around: only what is named may be written
defaults = true      # false throws the built-in rules away

[[policy.paths.rules]]
match  = [".ultraloom/runs/*", "uv.lock"]
reason = "An edited journal destroys what replay exists for."

[[policy.commands.rules]]
regex  = '(^|[\n;&|(`])\s*git\s+push(?![\w-])'
reason = "Whether commits reach the remote is a human's decision."

[[policy.content.rules]]
regex  = 'type:\s*ignore(?!\s*#)'
tools  = ["Write", "Edit"]
reason = "No type: ignore without a reason behind it."
```

A rule carries `match` (a glob) or `regex`, exactly one of the two — both at
once would be the question whether AND or OR is meant, and is refused when the
file is read. Either takes a string or a list of them, several patterns sharing
one reason, OR between them; an empty list is refused rather than kept as a rule
that never fires. `tools` is an optional filter, not a kind of its own: left
out, the rule holds for every tool of its kind. `reason` is mandatory, because a
block without one produces exactly the sort of message an agent argues with or
works around.

Write regexes as TOML literal strings ('...'). In a basic string every
backslash has to be doubled, and a forgotten one turns `\s` silently into `s`
— a rule that still loads and still matches, only something else.

Anchoring is where a command rule gets talked past. The value handed to the
matcher is the whole command line, `re.search` runs without `MULTILINE`, and so
`^` means the start of that line and nothing else: `^git push` blocks `git
push` and lets `git commit -m x && git push` through — which is the shape the
rule was written for in the first place. Let the alternatives in, and end the
word yourself: `` (^|[\n;&|(`])\s*git\s+push(?![\w-]) `` picks up `;`, `&&`, a
pipe, a subshell and a second line, while `(?![\w-])` keeps `git pushd` and
`git push-notes` out where a bare ``\b`` would take them.

Paths are matched as paths and everything else as flat text. A path pattern goes
through `PurePosixPath.full_match`, which is the only thing here that knows `**`
across directory boundaries — without it `.aws/**` is not a useful pattern — and
which keeps `config/*` from reaching `config/a/b`. For a command line that rule
would be wrong: the slash in `rm -rf a/b` separates no levels, so commands and
content go through `fnmatch`. Claude Code sends absolute paths; the hook makes
them relative to the project root and normalises separators to `/`, so one
pattern hits the same thing on Windows and on POSIX. What lies outside the root
stays absolute, and a rule aiming there has to spell the whole path.

The mode sits on the kind and not on the whole policy. A global `mode = "allow"`
would, along with the paths, forbid every command nobody happened to name —
useful for paths, unusable for commands.

In `deny` mode **every** matching rule is reported, not just the first: with
first-hit-wins the agent clears one reason, runs into the next, and needs a
round per rule for a decision it could have made completely the first time. In
`allow` mode the first permission ends the check, and a subject nothing permits
is refused with the note that the mode is `allow`.

### What is blocked without any configuration

With no `.ultraloom/config.toml` at all, the built-in rules still apply — a repo
is protected without anyone having set anything up. They are security only, and
they live as a constant in `ultraloom.policy.config`, not in a shipped TOML
file: a file can go missing, a constant cannot.

Paths, reason *secrets are not written by an agent*:

    .env   .env.*   *.pem   *.key   id_rsa*   *.p12
    .npmrc   .pypirc   credentials.json   .aws/**

Content, reason *this looks like a credential in plain text*:

    -----BEGIN [A-Z ]*PRIVATE KEY-----
    \bAKIA[0-9A-Z]{16}\b
    \bsk-[A-Za-z0-9]{20,}\b

Commands: none. `git push` and `pip` instead of `uv` are house rules, not
security, and belong in the project file where they can be seen. A built-in rule
nobody reads gets killed with `defaults = false` at the first friction, and
takes the real ones with it.

The built-ins come first in the list of reasons, then the project's rules in the
order of the file. They apply **only in `deny` mode**: whoever turns a kind
around to `allow` gets the allowlist and nothing else, the built-ins included.
Turning the mode around means taking the responsibility whole.

### Exit codes

    0  allowed, or the tool touches no rule at all
    1  internal error — never blocks; a broken policy must not lock up a session
    2  refused; every reason on stderr

**A broken configuration is exit 2, not exit 1.** A policy that passes silently
when its own configuration is unreadable is the same failure this README warns
about beside the coverage check: a line reading "ok" for something nobody
checked. Exit 1 stays reserved for real internal faults — an unreadable payload,
empty stdin.

As a Claude Code hook, in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|NotebookEdit|Bash|PowerShell",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project \"${CLAUDE_PROJECT_DIR}\" ultraloom policy hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

The hook reads `tool_name` first and exits 0 before touching a configuration
when the tool concerns no kind — it runs before every `Write`, `Edit`,
`NotebookEdit`, `Bash` and `PowerShell`, so its own cost is a requirement.
Every file tool yields a path subject and a content subject, but each spells
the two keys its own way:

| Tool           | path            | content      |
| -------------- | --------------- | ------------ |
| `Write`        | `file_path`     | `content`    |
| `Edit`         | `file_path`     | `new_string` |
| `NotebookEdit` | `notebook_path` | `new_source` |

`NotebookEdit` with `edit_mode = "delete"` yields the path only: its
`new_source` is required by the schema but never written, so a content rule
firing there would be a false alarm. `Bash` and `PowerShell` both yield their `command`, so
one rule of kind `commands` covers either shell — a `git push` rule that knew
only `Bash` was no rule at all on Windows.

`policy check` is the same decision without a payload around it, for a hand or a
script: `ultraloom policy check commands "git push origin master"`. `--tool`
says which tool name a `tools` filter should see; it defaults to `Write`.

The decision is drawn in `docs/flows/policy.md`.

## Commit messages

    ultraloom commit-msg <file>          # what the git hook runs
    ultraloom commit-msg --calibrate N   # what a threshold would have refused

A repository whose history is half English and half German is hard to read and
harder to search, and the drift is never a decision — it is one hurried commit
at a time. This is the gate that catches it while the message is still in the
editor.

**Opt-in, with no default.** Without a `[commit]` section in
`.ultraloom/config.toml` the message is not even read. There is no sensible
language to check against that nobody chose, so unlike `[policy.*]` this
section has no rule that applies without it.

### Configuration

```toml
[commit]
# Required. "en" or "de" — the language commits here are written in.
language = "en"

# Optional, default 2. Stopword hits on one line before it is refused.
threshold = 2

# Optional. Lines this project never wants scored, each with its reason.
[[commit.allow]]
regex  = '^Revert "'
reason = "A revert repeats the original subject verbatim, whatever it said."
```

`[[commit.allow]]` takes `regex` and `reason`, both required, and nothing else.
Unlike the policy's path rules there is no `match`: a glob has no clear meaning
against a line of text — would `WIP*` be the whole line or somewhere in it? —
and writing one is refused rather than quietly compiled as a regex, where
`WIP*` would become `WIP` followed by any number of `P`. The pattern is
compiled while the config is read, so a broken one fails immediately instead of
waiting for the commit that happens to match first.

Every value is checked when it is read, and a mistake is named together with
the file it came from. A broken `[commit]` is exit 1, not exit 2 — see the exit
codes below.

### The heuristic

Function words of the *other* language that mean nothing in this one. For
`language = "en"` the list is German: `der`, `das`, `und`, `nicht`, `ein`,
`wird`, `mit`, `von` and some forty more. Deliberately absent, each an ordinary
English word: `die`, `war`, `man`, `den`, `hat`, `in`, `so`, `an`. "Let the
process die in the war room" must not be a finding.

Hits are counted **per line, not per message**. A body listing two German page
titles is two lines of one hit each, not one line of two — and the second
reading would refuse it.

Umlauts are folded before matching (`ä` to `ae`, `ö` to `oe`, `ü` to `ue`, `ß`
to `ss`), so `für` and `fuer` are the same word to the check while the word
list itself stays ASCII.

### What is never scored

Lines starting with `#`, because git writes its own hints there, and everything
below the `# ------------------------ >8 ---` scissors that `git commit
--verbose` adds — the diff below it carries whatever the change touched, and
scoring it would refuse every commit that goes near prose in the other
language.

Within a line, five shapes are removed before the hits are counted:

| Shape          | Example                     | Why                                |
| -------------- | --------------------------- | ---------------------------------- |
| Trailer lines  | `Ref: das und der`          | A git trailer, not prose (not line 1) |
| Code spans     | `` `das und der` ``         | Quoted identifiers and output      |
| Quoted spans   | `He said "das und der"`     | A citation is not the author's own |
| Path tokens    | `docs/das/und.md`, `der.py` | A filename is not a sentence       |
| Name particles | `von Neumann`, `de Broglie` | The particle is part of a name     |

A trailer is the capitalised hyphenated shape — `Co-Authored-By`,
`Signed-off-by` — or one of `Fixes`, `Closes`, `Refs`, `Ref`, `Cc`, `Link`,
`Bug`, `BREAKING CHANGE`. Nothing else: a conventional-commit subject such as
`fix:` or `docs:` is prose and is scored.

Code spans and quoted spans may wrap across a line break, however many lines
they run: the check tracks whether a span is open as it walks the message, so
both halves are exempt and so is any line lying wholly inside. Scoring itself
stays per line — each line keeps its own count and its own threshold decision;
only the question of whether a span is open carries over.

A delimiter that pairs with nothing — a backtick or a `"` used as punctuation —
opens a span, and the rest of that line is read as quoted. That errs toward
letting a line through rather than refusing it, which is the safe direction.
Only the double quote delimits, so an apostrophe in `don't` opens nothing.

Lines that begin with `#` never move that state: git wrote them and strips
them again before the message is stored, so a delimiter there belongs to no
span the author wrote.

The exemption never applies to line 1. A trailer block does not begin on the
subject line, while `Ref:` and `Auto-merge:` are perfectly good subjects — and
for a one-line commit the subject is the whole message, so an exemption there
would switch the gate off exactly where it matters.

A name particle is the lowercase word followed by a capitalised one; German
prose puts an article or a lowercase noun there instead. Without this rule a
message citing two such names reaches the threshold on its own.

### Calibrating the threshold

No number carries from one repository to the next: a project whose commits
quote paths, package names or foreign titles reaches any threshold sooner than
one whose commits are plain prose. So measure before turning the gate on.

    ultraloom commit-msg --calibrate 100 --language en --root .

It reads the last `N` messages with `git log` and prints, per threshold, how
many it would have refused and their subjects. The same scan the hook runs
answers here, `[[commit.allow]]` included, or the table would report a cost the
configured gate never charges.

`--language` exists because a project that has not written `[commit]` yet has
no language to read — which is the whole point of measuring first. With a
`[commit]` section present the flag overrides it for this measurement only.
Given neither, the command refuses rather than guessing. A count below 1 is
refused too: `git log -n -1` means *unlimited* and `-n 0` prints an empty
table, so either would answer a typo with something that reads like a result.

`--language` belongs to `--calibrate` and to nothing else. `ultraloom
commit-msg <file> --language de` is an error, not a courtesy: the hook's
language must come from `[commit]`, because a flag that overrode it would let a
commit choose the rule it is judged by. `--calibrate` beside a message file is
refused for the milder reason that a flag should never be silently ignored.

**The German direction is not calibrated.** The word list for `language = "de"`
was written by hand and never measured against a German-language repository.
Its threshold is a starting point, not a result; measure it with `--calibrate`
before trusting it. The English direction was calibrated against one project's
history — a hundred English commits against sixteen German ones — and has a
second reading here: `--calibrate 100 --language en` over ultraloom itself on
2026-08-26 refuses exactly one of the last hundred messages, the same one at
threshold 1 and at threshold 2. That message is an English commit *about* the
stopword list which cites `das, und` bare in parentheses; it is the honest
limit of the heuristic, and the reason code spans and `[[commit.allow]]` exist.
Publishing a guessed number as a measured one would be exactly the failure this
tool argues against.

### Exit codes

    0  the message is fine, or the project has no [commit] section
    1  internal error — a broken config, an unreadable file, a misused flag
    2  refused; every offending line on stderr

**A broken configuration is exit 1 here, and exit 2 under the policy.** The
asymmetry is deliberate: the policy guards against a tool call that must not
happen, so silence there is the larger harm. This gate guards a style, and
blocking every commit in a repository over a typo in a TOML file is worse than
letting one through — the mistake surfaces at the next `ultraloom check`.

The refusal names every line it found, not just the first, with the hits that
scored it:

```
ultraloom commit-msg: this message reads as German, and commits here are English.
  line 1: Fix das und der thing
          hits: das, und, der
Rewrite it, or use `git commit --no-verify` if this cannot wait. The next
commit runs this check again.
```

All of them, because one at a time sends the author back through the editor per
line, and each trip is another chance to reach for `--no-verify`. And
`--no-verify` is named on purpose: a gate that hides its own way out gets one
built around it. The sentence after it is the point — the escape is for this
commit, not for the branch.

### The git hook

ultraloom ships the command, not the hook. Three lines make it one:

```sh
#!/usr/bin/env sh
exec ultraloom commit-msg "$1"
```

There is no `install` subcommand. A tool that writes into `.git/` or changes a
git setting unasked is the kind of side effect this project criticises
elsewhere; three lines in a README are honester.

A hook under `.git/hooks/` is not versioned and is missing from a fresh clone,
so keep the file in the repository instead and point git at it once per
checkout:

```sh
mkdir -p .githooks
# write the three lines above to .githooks/commit-msg, then:
chmod +x .githooks/commit-msg
git config core.hooksPath .githooks
```

`core.hooksPath` is per-clone configuration and cannot be committed, so the
`git config` line belongs in the project's setup instructions. What is
committed is the hook itself, so nobody has to reconstruct it.

Where ultraloom is not on `PATH`, spell the invocation out —
`exec uv run --project . ultraloom commit-msg "$1"` — and remember that git
runs the hook from the top of the working tree.

## Session hooks

    ultraloom hook session-start    # SessionStart
    ultraloom hook post-edit        # PostToolUse
    ultraloom hook subagent-start   # SubagentStart
    ultraloom hook subagent-stop    # SubagentStop
    ultraloom hook stop             # Stop

The policy answers *may this tool call happen*. These five hooks answer the
questions it cannot see: is the file that was just written in order, is the
work of this turn green before the turn ends, does a paused run still wait for
an answer, and what did a subagent do that its report left out. Each reads
Claude Code's payload from stdin, exactly like `ultraloom policy hook`.

| Event | Hook | What it does |
| ----- | ---- | ------------ |
| `SessionStart` | `session-start` | Names every run paused at a gate, with the question and the `ultraloom resume` line that answers it. Writes down the commit the session starts on. |
| `PostToolUse` | `post-edit` | Runs `ruff format` over the file that was written, then the `edit` profile. |
| `SubagentStart` | `subagent-start` | Records where `origin` and the local `HEAD` stood before the subagent ran. |
| `SubagentStop` | `subagent-stop` | Names every remote ref that moved, appeared or vanished, and every commit `HEAD` gained. |
| `Stop` | `stop` | Runs the chain -- or one profile, with `--checks` -- and holds the turn while anything is red. |

### What exit 2 means, per event

    0  in order, or deliberately skipped
    1  internal error — never holds anything up
    2  a finding; what that causes depends on the event

Exit 2 is not one thing, and getting it wrong is silent:

- At `Stop` it **holds the turn**. The agent is handed the findings and asked
  to go again.
- At `PostToolUse` it blocks nothing — the tool has already run. It is only
  how the finding reaches the file that caused it, instead of surfacing a
  minute later in the stop gate with nothing to connect it to.
- At `SessionStart` and `SubagentStart` it never happens; those two report and
  return 0.
- At `SubagentStop` it never happens **on purpose**. By the time it runs, the
  push has happened; stopping the subagent from stopping does not undo it.

A chain that could not run at all is exit 1, never exit 2 — but only if it
delivered *no* usable verdict, meaning **every** red result is `unavailable`.
One unavailable check beside a real finding is still exit 2. The narrower rule
was paid for: a GDScript project configures no `types` command, because the
language has no typechecker, so every run carried one unavailable result. Under
the older "any" reading the gate ran the full chain, found a genuine violation,
and exited 1 anyway — it could never block there. Missing check kinds are still
reported, they just no longer mask the findings beside them.

The distinction matters more here than anywhere: these hooks check ultraloom
with ultraloom, and a broken `checks.py` must not lock a session in.

### The stop gate

Three things keep it from becoming a trap:

- **The marker.** While `.claude/.no-verify` exists, the gate exits 0 without
  reading or running anything. For a turn somebody wants to end red on
  purpose.
- **The block counter.** At most `MAX_BLOCKS` = 3 blocks per session; after
  that the gate says it gave up and lets the turn end. A gate that never
  yields locks the session it was meant to protect, and from inside that
  session there is no way out. The counter is *not* cleared by a green pass —
  otherwise a session alternating red and green would never reach the cap.
- **The short circuit.** A turn that changed nothing exits 0 in about
  300 ms instead of spending a minute on a verdict that is already known.

What counts as *changed* is measured with `changed_since(root, base)`, not
against the working tree: a turn that **commits** its work leaves `git status`
with nothing to report, and a gate built on the working tree alone would go
quiet at exactly the moment somebody committed something unverified. The base
is written by `session-start` and moved forward by every green pass — never by
a blocked one, which would switch the gate off after a single finding. Was the
gate switched on mid-session, there is no base; `stop` then falls back to the
working tree **and says so**, because a measurement with a known blind spot
must not look like a complete one.

The gate subtracts its own state files from what it sees. Without that, every
turn after the first would look changed because of the file the gate itself
wrote.

### Running a profile instead of the whole chain

    ultraloom hook stop --checks edit

`--checks` takes what `ultraloom run --checks` takes: a profile name from
`[verify.profiles]`, or a comma-separated list of check kinds. Without it the
gate runs every kind, which is what it has always done.

The reason a project needs this is the split between checks that only *read*
the source and checks that *execute* it. In one game project a turn's end cost
36 minutes, almost all of it the Godot suite (639 s serially) and the coverage
report — paid again at the end of every single turn, including turns that
changed one line of documentation. Static checks belong to the edit and to the
turn; the suite and the coverage threshold execute the project and belong to
the commit, where that project's commit gate already runs them.

**A narrowed pass does not move the base.** The base is the gate's word for
"everything up to here has been verified", and a profile that skips the suite
has not verified it. Were the base moved anyway, the next turn would treat the
untested work as done and the suite would never run at any gate. So under
`--checks` the range only grows — which is affordable exactly because the
profile was chosen for being cheap.

An unknown profile or check kind is exit 1 with `kinds_for`'s own message, the
same one `ultraloom run --checks` prints. It never holds the turn: a broken
configuration is not a verdict about the work.

### Wiring

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run --project \"${CLAUDE_PROJECT_DIR}\" ultraloom hook stop --root \"${CLAUDE_PROJECT_DIR}\"",
            "timeout": 300
          }
        ]
      }
    ]
  }
}
```

`PostToolUse` takes the matcher `Write|Edit|NotebookEdit`; the other four match
everything. Timeouts: `post-edit` 60, `stop` 300, `session-start` 20,
`subagent-start` 30, `subagent-stop` 30.

**One entry per event, and this is not a matter of taste.** Several entries for
the same event start *concurrently*, not one after another — two measured
`Stop` entries started 2 ms apart and overlapped completely. A block counter
split across two entries loses increments, which is a gate that does not count.
Anything added later belongs in the same entry.

### The state directory

`.ultraloom/hooks/<session_id>.json` holds what has to survive between two
calls: the block counter, the session's base commit, and one remote snapshot
per subagent. One file per session, so two sessions in the same checkout do not
reset each other's counter.

It belongs in `.gitignore`, and it belongs in the policy's path rules: an agent
that resets its own block counter has abolished the gate.

The decision is drawn in `docs/flows/session-hooks.md`.

## The harness (optional)

    uv add "ultraloom[agent]"

Runs a flow as a graph: nodes are steps, edges are transitions with
conditions. It journals every step, stops at approval points, and resumes an
aborted run from where it stopped.

    ultraloom run <flow>       # start a flow; prints a run id
    ultraloom show <id>        # print that run's journal, one line per step
    ultraloom resume <id> --answer "yes"
    ultraloom replay <id>      # re-derive the run from its journal, no model call

### verify-until-green

The flow ultraloom ships with. It runs the checks, hands every red one to the
repairer, and runs them again — until everything is green, until nothing moves
any more, or until the round ceiling is reached.

    ultraloom run verify_until_green
    ultraloom run verify_until_green --checks lint,types
    ultraloom run verify_until_green --checks quick --max-rounds 5

Underscores on the command line: a flow name is a Python identifier, so
`ultraloom run verify-until-green` is refused with exit 1. The graph is still
called `verify-until-green` inside — only the invocation is not.

`--checks` takes a comma-separated list of check kinds, or the name of a
profile from `[verify.profiles]`. Left out, the flow runs every check.
`--max-rounds` caps the repair rounds; left out, the flow's own limit applies.
The flow itself checks both while it builds, and refuses to start with a
message naming what it expected — so a typo never turns into a long run.

The repairer may not touch the paths in `[verify].tests` — a check that goes
green because its test was edited is the one repair worth nothing. Coverage is
never repaired at all, for the same reason: closing a coverage gap means
writing tests.

Every repair is measured against the commit the run started on, so this flow
starts only inside a git repository; elsewhere there is nothing to measure
against, and a run begun without one would pause and then refuse every answer.
A `resume` of an older run whose marker names no commit is refused the same
way — start a new run instead.

```toml
[verify]
# Required by this flow: the paths the repairer must leave alone.
tests = ["tests"]
# Seconds a single check may take before it is cut off.
timeout = 600

[verify.profiles]
quick = ["lint", "types"]
full = ["lint", "types", "test", "coverage"]
```

Exit codes: `0` green, `1` still red after the last round, `3` waiting at an
approval point, `4` the run was stopped over the protected test paths — either
the repairer touched one, or the working tree could not be read to tell.

The flow is described at length — in English and German, side by side — in
`docs/flows/verify-until-green.md`.

### Writing a flow

A flow is a Python module at `.ultraloom/flows/<name>.py`. Its name must be a
plain identifier. The module defines two things at module level:

```python
from dataclasses import dataclass

from ultraloom.graph import END, CodeNode, GateNode, Graph


@dataclass(frozen=True, slots=True)
class Data:
    note: str = ""


flow: Graph[Data] = Graph("greet", start="write")
flow.add(CodeNode("write", lambda d: {"note": "hello"}))
flow.add(
    GateNode(
        "approve",
        question=lambda d: f"send {d.note!r}?",
        apply=lambda d, answer: {"note": answer},
    )
)
flow.edge("write", "approve")
# Every node needs a way out, including the last one: it leaves towards END.
flow.edge("approve", END)

initial = Data()
```

`flow` must be a `Graph`; `initial` is the frozen dataclass the run starts
from. The module is executed on every load and is never registered in
`sys.modules`.

### The journal, and what a resume replays

A `run` executes every node it reaches. The journal is read only while a walk
is *retracing* one: a `replay` retraces from the first entry to the last, a
`resume` retraces up to the point where the earlier run stopped and does real
work from there.

What is retraced is keyed on a node's *input* — its name and the data it saw —
not on its code. Edit a node in the middle of a run and replay, and you get the
old result back from the journal. Start a fresh run when a node changes.

So a loop does work even when it leaves its payload alone. `max_visits` raises
a node's ceiling so it may sit on a cycle, and every pass of that cycle really
executes — which is what a node that measures the outside world without
changing it needs.

### Exit codes

| code | meaning |
| ---- | ------- |
| 0 | the command succeeded; a flow run reached its end |
| 1 | a check failed, or the command could not be carried out |
| 2 | argparse rejected the command line (its own convention) |
| 3 | the flow paused at an approval point and is waiting for an answer |
| 4 | a flow stopped itself; verify-until-green uses it for the protected test paths |

## Licence

AGPL-3.0-or-later. See `LICENSE`.
