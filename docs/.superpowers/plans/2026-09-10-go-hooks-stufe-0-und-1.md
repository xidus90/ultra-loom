# Go-Hooks, Stufe 0 und 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der SessionStart-Hook läuft auf Claude Code in Go, und die drei ungemessenen Hostverträge sind beantwortet und aufgeschrieben.

**Architecture:** Ein hostunabhängiger Kern (`internal/sessions`, `internal/journal`, `internal/gitwork`) unter einer Adapternaht (`internal/hostio`), aufgerufen über `ulguard hook session-start --host <h> [--root <d>]`. Der Host kommt als Flag, nicht aus der Nutzlast: die vier zu portierenden Ereignisse tragen kein `tool_input`, an dem man ihn erkennen könnte. Der Python-Hook bleibt liegen, bis der Go-Hook grün ist; erst dann schaltet `ulinit` um.

**Tech Stack:** Go 1.22 (`go.mod`), Standardbibliothek plus `github.com/BurntSushi/toml` (bereits vorhanden). Keine neue Abhängigkeit.

**Spec:** `docs/.superpowers/specs/2026-09-10-go-hooks-drei-hosts-design.md`

**Zuschnitt:** Dieser Plan deckt Stufe 0 vollständig und Stufe 1 soweit ab, wie sie nicht von den Messungen aus Aufgabe 2 abhängt. Der Antigravity-Adapter für `session-start` steht bewusst **nicht** darin: ob `PreInvocation` überhaupt Kontext in das Modell schreiben kann, ist die Frage, die Aufgabe 2 beantwortet, und ein Adapter davor wäre geraten. Stufen 2 bis 5 bekommen eigene Pläne.

## Global Constraints

- Go 1.22, wie `go.mod` es sagt. Keine neue Abhängigkeit.
- TDD: der Test wird zuerst geschrieben und läuft zuerst rot.
- 100 % Coverage; jeder Ausschluss mit Begründung. Der Boden des Go-Baums liegt bei 98 % (`.ultraloom/config.toml`, Coverage-Lane).
- Statische Typen, kein `any` ohne Grund.
- Kommentare, Bezeichner, Fehlermeldungen und Commit-Nachrichten **englisch**. Prosa in `docs/` deutsch, `docs/.superpowers/` einsprachig.
- Kein `Co-Authored-By` auf ein Modell, keine Werbezeile im Commit.
- Gearbeitet wird in einem echten Worktree. Prüfung: `git rev-parse --show-toplevel` nennt das Verzeichnis, in dem man steht. Nennt es den Hauptcheckout, ist es keiner — dann teilt man Index und HEAD und `git add` schweigt über neue Dateien.
- Binaries **beim Namen**, nie `./ulinit` oder `./ulguard`: die Dateien sind gitignoriert und liegen im Wurzelverzeichnis, ein frischer Worktree hat sie nicht (Commit `5a61634`).
- Mehrzeilige Commit-Nachricht über eine Datei und `git commit -F`, nie über ein Heredoc. Die Datei liegt im Arbeitsbaum und heißt `commitmsg.txt` — die Endung `.txt` steht in `explicitIgnoredExtensions`, eine endungslose Datei löst dagegen die ganze post-edit-Kette aus.
- Vor **jedem** Commit `git diff --cached --stat` lesen und ansehen, was wirklich im Index liegt. Eine fremde Sitzung im selben Checkout leert den Index oder lässt etwas darin liegen.
- Ein Shell-Befehl, eine Frage. Keine langen `&&`-Ketten.
- Exit-Codes: 0 durchlassen, 1 interner Fehler ohne Halt, 2 blockieren. Für `session-start` gibt es nichts zu blockieren — es gibt 0 oder 1 zurück, niemals 2.

## File Structure

| Datei | Verantwortung |
|---|---|
| `internal/settings/merge.go` | ändern: `toolKey` liest `ulguard hook <x>` wie `ultraloom hook <x>` |
| `internal/sessions/state.go` | neu: `SessionState`, `ReadState`, `WriteState` — Port von `src/ultraloom/hooks/state.py` |
| `internal/journal/journal.go` | neu: `Entry`, `Journal.Entries` — Lesehälfte von `src/ultraloom/journal.py` |
| `internal/journal/gate.go` | neu: `PendingGate`, `Pending` — Port von `src/ultraloom/gate.py` |
| `internal/gitwork/gitwork.go` | neu: `HeadCommit`, `ErrIgnoredRoot` — Port von `worktree.py:head_commit` |
| `internal/hostio/hostio.go` | neu: `Payload`, `Host`, `ParseHost`, `FindRoot` |
| `internal/hostio/claude.go` | neu: Claude-Nutzlast lesen, Antwort schreiben |
| `internal/hostio/codex.go` | neu: die Naht — ein unbekannter Host fällt geschlossen |
| `cmd/guard/hook_session_start.go` | neu: der Unterbefehl |
| `cmd/guard/main.go` | ändern: Verteilung um `hook` erweitern |
| `cmd/init/run.go` | ändern: `hookEntries` schreibt `ulguard hook session-start` |

`internal/sessions` bekommt den Zustand und **kein** neues Paket: der Paketkommentar dort beschreibt diese Dateien schon („One file per session under `.ultraloom/hooks/`, which is what the Python hooks already write"), hält `StateDir` und trägt in `safeName` die nachgerechnete Regel aus `state.py` samt Unicode-Begründung. Ein zweites Paket hätte zwei Namensregeln für eine Datei.

---

### Task 1: `toolKey` erkennt `ulguard hook <x>`

`internal/settings/merge.go:407` gibt für `ultraloom hook stop --root …` den Schlüssel `hook_stop` zurück, für `ulguard hook stop --root …` dagegen `ulguard`. Die Eintragsidentität ist `(event, matcher, owner)`, und `find` (`:372`) vergleicht Kommandos über diesen Schlüssel. Ohne die Änderung tragen alle vier Ereignisse denselben Schlüssel, und ein Treffer entsteht nur noch zufällig über `firstOwnedIndex`.

**Files:**
- Modify: `internal/settings/merge.go:407-443`
- Test: `internal/settings/merge_test.go`

**Interfaces:**
- Consumes: nichts.
- Produces: `toolKey("ulguard hook session-start --root x") == "hook_session-start"`. Aufgabe 7 verlässt sich darauf.

- [ ] **Step 1: Write the failing test**

In `internal/settings/merge_test.go` anfügen:

```go
// toolKey is the entry identity `find` compares commands by. Both spellings
// name the same hook, so both must answer the same key: without this,
// `ulguard hook session-start` and `ulguard hook stop` are one key --
// "ulguard" -- and the four events collide.
func TestToolKeyReadsUlguardHooks(t *testing.T) {
	tests := []struct {
		command string
		want    string
	}{
		{`ultraloom hook session-start --root "x"`, "hook_session-start"},
		{`ulguard hook session-start --root "x"`, "hook_session-start"},
		{`ulguard hook stop --root "x"`, "hook_stop"},
		{`ulguard.exe hook stop --root "x"`, "hook_stop"},
		// Not a hook subcommand: the bare name stays the key, so the write
		// barrier and the post-edit lane keep the slots they have.
		{`ulguard --root "x"`, "ulguard"},
		{`ulguard post-edit --root "x"`, "post-edit"},
	}
	for _, tt := range tests {
		if got := toolKey(tt.command); got != tt.want {
			t.Errorf("toolKey(%q) = %q, want %q", tt.command, got, tt.want)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/settings/ -run TestToolKeyReadsUlguardHooks -v`
Expected: FAIL — `toolKey("ulguard hook session-start --root \"x\"") = "ulguard", want "hook_session-start"`

- [ ] **Step 3: Write minimal implementation**

In `internal/settings/merge.go` die `ultraloom`-Verzweigung um den zweiten Namen erweitern:

```go
		// `ulguard` beside `ultraloom`, because the hook subcommands are
		// moving from the Python entry point to the Go binary and both
		// spellings name the same hook. Without this the four events share
		// one key and `find` matches them by position instead of by command.
		if (clean == "ultraloom" || clean == "ulguard") && i+1 < len(words) {
			sub := strings.ToLower(strings.Trim(words[i+1], `"'`))
			if (sub == "hook" || sub == "policy") && i+2 < len(words) {
				return sub + "_" + strings.ToLower(strings.Trim(words[i+2], `"'`))
			}
			return sub
		}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/settings/`
Expected: ok. Die vorhandenen Tests in dieser Datei müssen mitlaufen — `ulguard --root "x"` fiel bisher auf `return clean` und muss weiter `ulguard` antworten, `ulguard post-edit` weiter `post-edit`.

- [ ] **Step 5: Commit**

Nachricht nach `commitmsg.txt` schreiben, dann:

```bash
git add internal/settings/merge.go internal/settings/merge_test.go
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 2: Die drei Hostverträge messen

Kein Code. Das Ergebnis sind drei belegte Antworten im Spec, und sie entscheiden, was Stufe 1 für Antigravity überhaupt bauen kann. Vorbild ist ultra-brains Messung vom 2026-09-06, die feststellte, dass die deny-Hülle auf stdout **nicht** gelesen wurde und erst Exit 2 wirkte (`ultra-brain/hooks/guard.sh`).

**Files:**
- Modify: `docs/.superpowers/specs/2026-09-10-go-hooks-drei-hosts-design.md` (Abschnitt „Zwei ungemessene Punkte, Stufe 0" — Titel auf drei anpassen und die Antworten eintragen)
- Create: `docs/.superpowers/specs/2026-09-10-antigravity-hook-messung.md` (das Protokoll)

**Interfaces:**
- Consumes: nichts.
- Produces: drei Antworten. Aufgabe 6 liest die erste (bestimmt, ob der Antigravity-Adapter eine Hülle schreiben muss oder nur einen Exit-Code), der Folgeplan die anderen zwei.

- [ ] **Step 1: Prüfhook anlegen**

Ein Probe-Repo außerhalb von ultraloom, damit keine echte Konfiguration verbogen wird:

```bash
mkdir -p /c/Users/micro/AppData/Local/Temp/agy-probe/.agents
```

`/c/Users/micro/AppData/Local/Temp/agy-probe/probe.sh`:

```bash
#!/usr/bin/env bash
# Records what the host handed over, then answers in one of three ways
# chosen by PROBE_MODE, so each answer path can be told apart.
set -u
cat > "$(dirname "$0")/payload-$(date +%s%N).json"
case "${PROBE_MODE:-envelope}" in
  envelope)
    echo '{"decision": "deny", "reason": "probe: envelope only", "hookSpecificOutput": {"hookEventName": "Stop", "permissionDecision": "deny", "permissionDecisionReason": "probe: envelope only"}}'
    exit 0
    ;;
  exit2)
    echo "probe: exit 2 on stderr" >&2
    exit 2
    ;;
  context)
    echo '{"hookSpecificOutput": {"hookEventName": "PreInvocation", "additionalContext": "PROBE-CONTEXT-MARKER-7f3a"}}'
    exit 0
    ;;
esac
```

`/c/Users/micro/AppData/Local/Temp/agy-probe/.agents/hooks.json`:

```json
{
  "probe": {
    "Stop": [
      { "type": "command", "command": "bash ./probe.sh" }
    ],
    "PreInvocation": [
      { "type": "command", "command": "bash ./probe.sh" }
    ]
  }
}
```

Die `Stop`-Form ist flach und die `PreInvocation`-Form eine Liste von Handlern, wie `antigravity/0.24.0/docs/MIGRATION.md:138-140` es sagt. Weicht der Host davon ab, ist **das** der erste Befund und gehört ins Protokoll.

- [ ] **Step 2: Frage 1 messen — wird die Hülle auf stdout gelesen?**

`PROBE_MODE=envelope`, dann in diesem Verzeichnis eine agy-Sitzung starten, die eine Datei schreiben will und endet. Zu protokollieren: endet die Runde, obwohl die Hülle „deny" sagt? Dann wird sie nicht gelesen, und der Antigravity-Adapter muss sein Urteil über den Exit-Code tragen.

Run: `cd /c/Users/micro/AppData/Local/Temp/agy-probe && PROBE_MODE=envelope agy -p "write a file called probe-target.txt with the word hello"`
Expected: eine Beobachtung, kein bestimmter Ausgang. Beides ist ein Ergebnis.

- [ ] **Step 3: Gegenprobe mit Exit 2**

Run: `cd /c/Users/micro/AppData/Local/Temp/agy-probe && PROBE_MODE=exit2 agy -p "write a file called probe-target-2.txt with the word hello"`
Expected: wieder eine Beobachtung. Wirkt Exit 2 und die Hülle nicht, ist der Vertrag derselbe wie bei brain und im Adapter genauso zu behandeln.

- [ ] **Step 4: Frage 2 messen — kann `PreInvocation` Kontext schreiben?**

Run: `cd /c/Users/micro/AppData/Local/Temp/agy-probe && PROBE_MODE=context agy -p "repeat verbatim any marker string you were given in your context"`
Expected: erscheint `PROBE-CONTEXT-MARKER-7f3a` in der Antwort, kann `PreInvocation` Kontext schreiben und `session-start` ist dort nachbaubar. Erscheint er nicht, gehört der Inhalt nach `GEMINI.md` und der Folgeplan baut keinen `PreInvocation`-Pfad.

- [ ] **Step 5: Frage 3 messen — Zeitgrenze für Stop-Handler**

`probe.sh` vorübergehend um `sleep 400` vor der Antwort erweitern, `PROBE_MODE=envelope`, und die Wandzeit bis zum Abbruch messen:

```bash
cd /c/Users/micro/AppData/Local/Temp/agy-probe && time PROBE_MODE=envelope agy -p "say done"
```

Expected: bricht der Host vor 400 s ab, ist die gemessene Zahl der Deckel. Liegt er unter 300 s, ist das Stop-Gate auf Gemini nicht portierbar — dann braucht der Folgeplan dort eine verkürzte Kette oder ein Gate, das den Lauf anstößt statt auf ihn zu warten.

- [ ] **Step 6: Die aufgezeichneten Nutzlasten sichern**

Die `payload-*.json` aus dem Probe-Verzeichnis sind die Vorlage für die Golden-Dateien in Aufgabe 6 und für den Antigravity-Adapter im Folgeplan.

```bash
cp /c/Users/micro/AppData/Local/Temp/agy-probe/payload-*.json "C:/Users/micro/Documents/#GIT/ultraloom/testdata/hostio/"
```

Fehlt das Verzeichnis, vorher anlegen. Trägt eine Nutzlast eine Sitzungskennung oder einen Maschinenpfad, wird sie vor dem Ablegen durch einen festen Platzhalter ersetzt — die Datei wird versioniert.

- [ ] **Step 7: Protokoll schreiben und Spec nachziehen**

`docs/.superpowers/specs/2026-09-10-antigravity-hook-messung.md` mit Datum, Uhrzeit, agy-Version (`agy --version`), den drei Fragen, den Befehlen, der beobachteten Antwort und der Schlussfolgerung. Eine Frage, die nicht messbar war, wird als nicht messbar notiert — nicht als beantwortet.

Dann im Spec den Abschnitt „Zwei ungemessene Punkte, Stufe 0" auf drei korrigieren und je Punkt die Antwort samt Verweis auf das Protokoll eintragen.

- [ ] **Step 8: Commit**

```bash
git add docs/.superpowers/specs/2026-09-10-antigravity-hook-messung.md docs/.superpowers/specs/2026-09-10-go-hooks-drei-hosts-design.md testdata/hostio/
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 3: `internal/sessions` liest und schreibt den Sitzungszustand

Port von `src/ultraloom/hooks/state.py`. Das Paket hält `StateDir` und `safeName` bereits; hier kommt der Inhalt der Datei dazu.

**Files:**
- Create: `internal/sessions/state.go`
- Test: `internal/sessions/state_test.go`

**Interfaces:**
- Consumes: `sessions.StateDir`, `sessions.safeName` (paketintern).
- Produces:
  - `type SessionState struct { Blocks int; Snapshots map[string]string; Base string }`
  - `func ReadState(root, sessionID string) SessionState`
  - `func WriteState(root, sessionID string, state SessionState) error`

`Base` ist `string` und nicht `*string`: `state.py` unterscheidet `None` von einem Wert, und der leere String ist in dieser Datei nie ein gültiger Commit — beide Fälle fallen also zusammen, ohne dass ein Zeiger dafür nötig wäre. Beim Schreiben wird der leere String als JSON-`null` ausgegeben, damit Python die Datei weiter liest.

- [ ] **Step 1: Write the failing test**

`internal/sessions/state_test.go`:

```go
package sessions

import (
	"os"
	"path/filepath"
	"testing"
)

// A file that cannot be read counts as empty, exactly as state.py decides:
// raising would end every turn with an internal error over a counter whose
// worst case is three extra rounds.
func TestReadStateOfBrokenFileIsEmpty(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, filepath.FromSlash(StateDir))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "s1.json"), []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}

	got := ReadState(root, "s1")

	if got.Blocks != 0 || got.Base != "" || len(got.Snapshots) != 0 {
		t.Fatalf("a damaged file reads as empty, got %+v", got)
	}
}

func TestReadStateOfMissingFileIsEmpty(t *testing.T) {
	if got := ReadState(t.TempDir(), "nobody"); got.Blocks != 0 || got.Base != "" {
		t.Fatalf("an absent file reads as empty, got %+v", got)
	}
}

// The shape check is state.py's: a `blocks` that is not a number or a
// `snapshots` that is not an object makes the whole file empty rather than
// half-trusted.
func TestReadStateOfWrongShapeIsEmpty(t *testing.T) {
	root := t.TempDir()
	writeRaw(t, root, "s1", `{"blocks": "three", "snapshots": {}, "base": null}`)

	if got := ReadState(root, "s1"); got.Blocks != 0 {
		t.Fatalf("a wrong shape reads as empty, got %+v", got)
	}
}

// A file written before `base` existed keeps its counter. state.py reads that
// field with `get` and not `[...]` for this reason, and the note beside it
// says so.
func TestReadStateWithoutBaseKeepsBlocks(t *testing.T) {
	root := t.TempDir()
	writeRaw(t, root, "s1", `{"blocks": 2, "snapshots": {"a": "b"}}`)

	got := ReadState(root, "s1")

	if got.Blocks != 2 || got.Base != "" || got.Snapshots["a"] != "b" {
		t.Fatalf("expected blocks 2 and no base, got %+v", got)
	}
}

func TestWriteStateThenReadBack(t *testing.T) {
	root := t.TempDir()
	want := SessionState{Blocks: 1, Snapshots: map[string]string{"n": "abc"}, Base: "deadbeef"}

	if err := WriteState(root, "s1", want); err != nil {
		t.Fatal(err)
	}
	got := ReadState(root, "s1")

	if got.Blocks != 1 || got.Base != "deadbeef" || got.Snapshots["n"] != "abc" {
		t.Fatalf("round trip lost something: %+v", got)
	}
}

// Python must keep reading these files while both sides run: an absent base is
// JSON null there, never "".
func TestWriteStateSpellsAnAbsentBaseAsNull(t *testing.T) {
	root := t.TempDir()
	if err := WriteState(root, "s1", SessionState{}); err != nil {
		t.Fatal(err)
	}

	raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(StateDir), "s1.json"))
	if err != nil {
		t.Fatal(err)
	}
	if want := `{"base":null,"blocks":0,"snapshots":{}}`; string(raw) != want {
		t.Fatalf("got %s, want %s", raw, want)
	}
}

// The id comes from outside, so it may not decide where the file lands. Same
// rule as safeName, checked through the public door.
func TestWriteStateKeepsATraversingIdInside(t *testing.T) {
	root := t.TempDir()
	if err := WriteState(root, "../../escape", SessionState{Blocks: 1}); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(StateDir), "escape.json")); err != nil {
		t.Fatalf("expected the file inside the state directory: %v", err)
	}
}

func writeRaw(t *testing.T, root, sessionID, body string) {
	t.Helper()
	dir := filepath.Join(root, filepath.FromSlash(StateDir))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, sessionID+".json"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/sessions/ -run TestReadState -v`
Expected: FAIL — `undefined: ReadState`, `undefined: SessionState`

- [ ] **Step 3: Write minimal implementation**

`internal/sessions/state.go`:

```go
package sessions

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// SessionState is state.py's SessionState: the counter, the snapshots and the
// base commit one session carries between two hook calls.
//
// Base is a string and not a pointer. state.py tells None from a value, and
// the empty string is never a commit any of these files could hold, so both
// absences are one. What must not collapse is the file: an absent base is
// written as JSON null, because the Python side keeps reading these files for
// as long as both sides run.
type SessionState struct {
	Blocks    int
	Snapshots map[string]string
	Base      string
}

// stateFile is the shape on disk, in the spelling state.py wrote and reads.
// Pointers, because a missing key and a null must both arrive as absent: a
// file written before `base` existed still carries a block counter, and
// reading it as damaged would throw that counter away.
type stateFile struct {
	Blocks    *int               `json:"blocks"`
	Snapshots *map[string]string `json:"snapshots"`
	Base      *string            `json:"base"`
}

// ReadState is state.py's `read`: what this session left behind, or an empty
// state.
//
// Every failure answers empty and none of them is reported. Raising would end
// a turn over a counter whose worst case is a few extra rounds, which is the
// trade state.py wrote down and this port keeps.
func ReadState(root, sessionID string) SessionState {
	raw, err := os.ReadFile(statePath(root, sessionID))
	if err != nil {
		return SessionState{}
	}
	var file stateFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return SessionState{}
	}
	// blocks and snapshots are required, base is not: the first two have been
	// in the file since it existed, so their absence is damage, while a file
	// from before `base` is merely older.
	if file.Blocks == nil || file.Snapshots == nil {
		return SessionState{}
	}
	state := SessionState{Blocks: *file.Blocks, Snapshots: *file.Snapshots}
	if file.Base != nil {
		state.Base = *file.Base
	}
	return state
}

// WriteState is state.py's `write`: keep this state for the next call.
func WriteState(root, sessionID string, state SessionState) error {
	path := statePath(root, sessionID)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("creating the directory for %s: %w", path, err)
	}
	snapshots := state.Snapshots
	if snapshots == nil {
		// `{}` and not `null`: state.py refuses a snapshots field that is not
		// an object and would read the whole file as damaged.
		snapshots = map[string]string{}
	}
	file := stateFile{Blocks: &state.Blocks, Snapshots: &snapshots}
	if state.Base != "" {
		base := state.Base
		file.Base = &base
	}
	// Marshal sorts object keys, which is what state.py's `sort_keys=True`
	// does: two writers must not produce two byte sequences for one state.
	body, err := json.Marshal(file)
	if err != nil {
		return fmt.Errorf("encoding the state of session %s: %w", sessionID, err)
	}
	if err := os.WriteFile(path, body, 0o644); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	return nil
}

func statePath(root, sessionID string) string {
	return filepath.Join(root, filepath.FromSlash(StateDir), safeName(sessionID)+".json")
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/sessions/`
Expected: ok

Prüfen, dass die Rundreise auch über die Sprachgrenze hält — Python muss lesen, was Go schreibt:

Run: `go test ./internal/sessions/ -run TestWriteStateSpellsAnAbsentBaseAsNull -v`
Expected: PASS. Schlägt es an der Schlüsselreihenfolge fehl, ist `json.Marshal` die Referenz und der erwartete String im Test anzupassen — nicht die Implementierung.

- [ ] **Step 5: Coverage prüfen**

Run: `go test ./internal/sessions/ -coverprofile=cov.out`
Run: `go tool cover -func=cov.out | grep -E "ReadState|WriteState|statePath"`
Expected: 100 % für alle drei. Fehlt ein Zweig, fehlt ein Test — nicht ein Ausschluss.

- [ ] **Step 6: Commit**

```bash
git add internal/sessions/state.go internal/sessions/state_test.go
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 4: `internal/journal` liest Journal und offenen Gate

Nur die Lesehälfte. `session-start` schreibt nichts ins Journal, und `input_hash` samt `append` gehört zu den Stufen, die den Lauf ausführen.

**Files:**
- Create: `internal/journal/journal.go`
- Create: `internal/journal/gate.go`
- Test: `internal/journal/journal_test.go`
- Test: `internal/journal/gate_test.go`

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `type Entry struct { Node, Kind, InputHash string; Delta map[string]any; Outcome string; Tools, Effort *string; Tokens int; Seconds float64; Detail *string }`
  - `func Entries(path string) ([]Entry, error)`
  - `type PendingGate struct { Node, Question, InputHash string }`
  - `func Pending(path string) (*PendingGate, error)` — `nil, nil` heißt: nichts wartet.

`Delta` ist `map[string]any`, weil das Journal beliebige Knotenausgaben trägt; das ist der eine begründete `any` in diesem Plan. `Tools`, `Effort` und `Detail` sind Zeiger, weil `journal.py` dort `str | None` schreibt und `Detail is None` in `pending_gate` eine Entscheidung trägt.

- [ ] **Step 1: Write the failing test für das Journal**

`internal/journal/journal_test.go`:

```go
package journal_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/journal"
)

const pausedLine = `{"delta":{},"detail":"which colour?","effort":null,"input_hash":"h1","kind":"gate","node":"ask","outcome":"paused","seconds":0.1,"tokens":0,"tools":null}`

const okLine = `{"delta":{"n":1},"detail":null,"effort":"low","input_hash":"h0","kind":"work","node":"build","outcome":"ok","seconds":2.5,"tokens":12,"tools":"bash"}`

// An absent file reads as empty and is not an error: journal.py's `entries`
// decides this, and a session that never ran anything still starts.
func TestEntriesOfMissingFileIsEmpty(t *testing.T) {
	got, err := journal.Entries(filepath.Join(t.TempDir(), "nothing.jsonl"))
	if err != nil {
		t.Fatalf("an absent file is not an error: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("expected no entries, got %d", len(got))
	}
}

func TestEntriesReadsInOrderAndSkipsBlankLines(t *testing.T) {
	path := write(t, okLine+"\n\n"+pausedLine+"\n")

	got, err := journal.Entries(path)
	if err != nil {
		t.Fatal(err)
	}

	if len(got) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(got))
	}
	if got[0].Node != "build" || got[1].Node != "ask" {
		t.Fatalf("order lost: %s then %s", got[0].Node, got[1].Node)
	}
	if got[0].Tools == nil || *got[0].Tools != "bash" {
		t.Fatalf("tools not read: %+v", got[0].Tools)
	}
	if got[1].Tools != nil {
		t.Fatalf("a null tools is absent, got %q", *got[1].Tools)
	}
	if got[0].Delta["n"] != float64(1) {
		t.Fatalf("delta not read: %+v", got[0].Delta)
	}
}

// A damaged line is named with its number and not swallowed. journal.py raises
// JournalError with exactly this shape, and session_start.py prints it and
// carries on with the other runs.
func TestEntriesNamesTheDamagedLine(t *testing.T) {
	path := write(t, okLine+"\n{not json\n")

	_, err := journal.Entries(path)

	if err == nil {
		t.Fatal("expected an error for a line that is not an entry")
	}
	if !strings.Contains(err.Error(), "line 2") {
		t.Fatalf("the error names the line number, got %v", err)
	}
}

func write(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "run.jsonl")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/journal/ -v`
Expected: FAIL — das Paket existiert nicht.

- [ ] **Step 3: Write the journal implementation**

`internal/journal/journal.go`:

```go
// Package journal reads the run journal: one JSONL line per node.
//
// The reading half only. `session-start` announces what is waiting and writes
// nothing, and the writer -- with the input hashing a resume depends on --
// belongs to the stages that walk a run.
package journal

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Entry is journal.py's Entry, field for field, in the JSON spelling on disk.
//
// Tools, Effort and Detail are pointers because the Python side writes
// `str | None` there and the difference carries a decision: `Pending` reads a
// nil Detail as "this pause asked nothing", which is not the same as an empty
// question.
type Entry struct {
	Node      string         `json:"node"`
	Kind      string         `json:"kind"`
	InputHash string         `json:"input_hash"`
	Delta     map[string]any `json:"delta"`
	Outcome   string         `json:"outcome"`
	Tools     *string        `json:"tools"`
	Effort    *string        `json:"effort"`
	Tokens    int            `json:"tokens"`
	Seconds   float64        `json:"seconds"`
	Detail    *string        `json:"detail"`
}

// Entries is journal.py's `entries`: every line, in order.
//
// An absent file is empty and not an error, and a line that is not an entry is
// named with its number. Both are that module's decisions: a run that never
// started has no journal, and a damaged line is a finding worth pointing at
// rather than a reason to hide the lines around it.
func Entries(path string) ([]Entry, error) {
	file, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("reading %s: %w", path, err)
	}
	defer file.Close()

	var found []Entry
	scanner := bufio.NewScanner(file)
	// A journal line carries a node's delta and outgrows the default 64 KiB
	// token. 4 MiB is the ceiling; a line beyond it is reported as damaged
	// rather than silently cut, which the scanner's own error does.
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for number := 1; scanner.Scan(); number++ {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		var entry Entry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			return nil, fmt.Errorf("%s: line %d is not a journal entry: %w", path, number, err)
		}
		found = append(found, entry)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("reading %s: %w", path, err)
	}
	return found, nil
}
```

- [ ] **Step 4: Run journal tests to verify they pass**

Run: `go test ./internal/journal/ -v`
Expected: PASS für die drei Journal-Tests.

- [ ] **Step 5: Write the failing test für den Gate**

`internal/journal/gate_test.go`:

```go
package journal_test

import (
	"testing"

	"github.com/xidus90/ultra-loom/internal/journal"
)

// Only the last entry decides, and only when it paused: gate.py reads the tail
// and nothing else.
func TestPendingReadsTheLastEntry(t *testing.T) {
	path := write(t, okLine+"\n"+pausedLine+"\n")

	gate, err := journal.Pending(path)
	if err != nil {
		t.Fatal(err)
	}

	if gate == nil {
		t.Fatal("expected an open gate")
	}
	if gate.Node != "ask" || gate.Question != "which colour?" || gate.InputHash != "h1" {
		t.Fatalf("unexpected gate: %+v", gate)
	}
}

func TestPendingIsNilWhenTheRunMovedOn(t *testing.T) {
	path := write(t, pausedLine+"\n"+okLine+"\n")

	gate, err := journal.Pending(path)
	if err != nil {
		t.Fatal(err)
	}
	if gate != nil {
		t.Fatalf("a run whose last entry is ok waits for nothing, got %+v", gate)
	}
}

func TestPendingIsNilForAnEmptyJournal(t *testing.T) {
	gate, err := journal.Pending(write(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	if gate != nil {
		t.Fatalf("an empty journal waits for nothing, got %+v", gate)
	}
}

// A pause with no question is not an address anyone can answer, so it is not
// reported as one. gate.py tests `last.detail is None` for this.
func TestPendingIsNilWhenThePauseAskedNothing(t *testing.T) {
	path := write(t, `{"delta":{},"detail":null,"effort":null,"input_hash":"h1","kind":"gate","node":"ask","outcome":"paused","seconds":0.1,"tokens":0,"tools":null}`+"\n")

	gate, err := journal.Pending(path)
	if err != nil {
		t.Fatal(err)
	}
	if gate != nil {
		t.Fatalf("a pause without a question is no open gate, got %+v", gate)
	}
}

func TestPendingPassesTheJournalErrorOn(t *testing.T) {
	if _, err := journal.Pending(write(t, "{not json\n")); err == nil {
		t.Fatal("a damaged journal must not read as nothing waiting")
	}
}
```

- [ ] **Step 6: Run gate test to verify it fails**

Run: `go test ./internal/journal/ -run TestPending -v`
Expected: FAIL — `undefined: journal.Pending`

- [ ] **Step 7: Write the gate implementation**

`internal/journal/gate.go`:

```go
package journal

// PendingGate is gate.py's PendingGate: a gate that stopped a run and is
// waiting for an answer.
//
// InputHash identifies the visit and not the node. A gate on a cycle pauses
// once per pass, and an answer addressed only to the node name would be spent
// on the first pass -- which the journal has already answered -- instead of on
// the pause that is actually open.
type PendingGate struct {
	Node      string
	Question  string
	InputHash string
}

// Pending is gate.py's `pending_gate`: the open question of this run, or nil.
//
// A damaged journal comes back as an error and never as "nothing waiting": a
// run whose journal cannot be read is not a run that has been answered.
func Pending(path string) (*PendingGate, error) {
	entries, err := Entries(path)
	if err != nil {
		return nil, err
	}
	if len(entries) == 0 {
		return nil, nil
	}
	last := entries[len(entries)-1]
	if last.Outcome != "paused" || last.Detail == nil {
		return nil, nil
	}
	return &PendingGate{Node: last.Node, Question: *last.Detail, InputHash: last.InputHash}, nil
}
```

- [ ] **Step 8: Run tests and check coverage**

Run: `go test ./internal/journal/ -coverprofile=cov.out`
Run: `go tool cover -func=cov.out`
Expected: ok, 100 % für `Entries` und `Pending`. Der Zweig `scanner.Err()` braucht einen Test — eine Zeile über 4 MiB erzeugt ihn:

```go
func TestEntriesRefusesAnOverlongLine(t *testing.T) {
	huge := `{"node":"` + strings.Repeat("x", 5*1024*1024) + `"}`
	if _, err := journal.Entries(write(t, huge+"\n")); err == nil {
		t.Fatal("a line beyond the buffer is damage, not silence")
	}
}
```

- [ ] **Step 9: Commit**

```bash
git add internal/journal/
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 5: `internal/gitwork.HeadCommit`

Port von `worktree.py:head_commit` samt der Verweigerung, die davor steht.

**Files:**
- Create: `internal/gitwork/gitwork.go`
- Test: `internal/gitwork/gitwork_test.go`

**Interfaces:**
- Consumes: `gitenv.Environ()`.
- Produces:
  - `func HeadCommit(root string) (string, error)`
  - `var ErrIgnoredRoot = errors.New(...)` — für Aufrufer, die den Fall unterscheiden wollen.

- [ ] **Step 1: Write the failing test**

`internal/gitwork/gitwork_test.go`:

```go
package gitwork_test

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/gitwork"
)

func TestHeadCommitOfARepository(t *testing.T) {
	root := repo(t)
	commit(t, root, "first")

	got, err := gitwork.HeadCommit(root)
	if err != nil {
		t.Fatal(err)
	}

	// The full SHA and not --short: the answer travels in a run marker and is
	// read back rounds later, and an abbreviation is only unique for as long
	// as the repository stays the size it was.
	if len(got) != 40 {
		t.Fatalf("expected a full 40-character sha, got %q", got)
	}
}

func TestHeadCommitOutsideARepository(t *testing.T) {
	if _, err := gitwork.HeadCommit(t.TempDir()); err == nil {
		t.Fatal("a directory that is not a repository has no head")
	}
}

// `git init` leaves HEAD naming a branch that does not exist yet. That is a
// repository without an answer, not an answer.
func TestHeadCommitOfARepositoryWithoutACommit(t *testing.T) {
	if _, err := gitwork.HeadCommit(repo(t)); err == nil {
		t.Fatal("a repository with no commit has no head")
	}
}

// The one refusal that has to come first. An ignored directory *is* inside a
// repository, so rev-parse answers readily with the surrounding repository's
// HEAD -- and measuring against that is worse than not measuring, because
// every file of the parked copy then reads as somebody's change.
func TestHeadCommitRefusesAnIgnoredRoot(t *testing.T) {
	outer := repo(t)
	commit(t, outer, "first")
	parked := filepath.Join(outer, "parked")
	if err := os.MkdirAll(parked, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outer, ".gitignore"), []byte("parked/\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := gitwork.HeadCommit(parked)

	if !errors.Is(err, gitwork.ErrIgnoredRoot) {
		t.Fatalf("expected ErrIgnoredRoot, got %v", err)
	}
}

func repo(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	run(t, root, "init")
	run(t, root, "config", "user.email", "t@example.invalid")
	run(t, root, "config", "user.name", "Test")
	return root
}

func commit(t *testing.T, root, message string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte(message), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, root, "add", "a.txt")
	run(t, root, "commit", "-m", message)
}

func run(t *testing.T, root string, args ...string) {
	t.Helper()
	command := exec.Command("git", args...)
	command.Dir = root
	// The same strip the package under test uses: without it a GIT_DIR in the
	// environment of the test runner would send these calls at the repository
	// this suite lives in.
	command.Env = append(os.Environ()[:0:0], stripped()...)
	if out, err := command.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}
```

Dazu der Helfer, der den Import sichtbar macht:

```go
// The same strip the package under test uses. Its own function so the reason
// stands in one place: a GIT_DIR in the test runner's environment outranks
// command.Dir, and without the strip these fixtures would be built inside the
// repository this suite lives in.
func stripped() []string { return gitenv.Environ() }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/gitwork/ -v`
Expected: FAIL — das Paket existiert nicht.

- [ ] **Step 3: Write minimal implementation**

`internal/gitwork/gitwork.go`:

```go
// Package gitwork answers what git knows about a working tree.
//
// Its own package because more than one hook asks: session-start records the
// commit a session begins on, and the stop gate measures against it. The
// Python original is src/ultraloom/worktree.py.
package gitwork

import (
	"errors"
	"fmt"
	"os/exec"
	"strings"

	"github.com/xidus90/ultra-loom/internal/gitenv"
)

// ErrIgnoredRoot is a root git answers about but never answers with.
var ErrIgnoredRoot = errors.New("git ignores this root, so it can never report a change there")

// HeadCommit is worktree.py's `head_commit`: the commit a run starts on, as
// git spells it.
//
// `rev-parse HEAD` and not `--short`: the answer travels in a run marker and
// is read back rounds later, and an abbreviated SHA is only unique for as long
// as the repository stays the size it was.
//
// Three ways of having no answer, all of them errors: no repository, a
// repository without a commit -- `git init` leaves HEAD naming a branch that
// does not exist yet -- and a root git ignores. The last one is why the ignore
// check runs first: such a directory *is* inside a repository, so rev-parse
// answers readily with the surrounding repository's HEAD, and measuring
// against that is worse than not measuring, because every file of the parked
// copy then reads as somebody's change.
func HeadCommit(root string) (string, error) {
	if ignored(root) {
		return "", fmt.Errorf("%s: %w -- run ultraloom in a working tree of its own", root, ErrIgnoredRoot)
	}
	out, err := git(root, "rev-parse", "HEAD")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}

// ignored is worktree.py's `_refuse_if_ignored`, and it reads the exit code
// itself rather than going through `git` below: `check-ignore` exits 1 for a
// path it does not ignore, which is the ordinary case and no failure at all.
// Every other code is read as "not ignored" on purpose -- the call that
// follows refuses a directory git cannot answer about anyway, and turning the
// difference between 1 and 128 into a second way of failing here would only
// make that refusal less clear.
func ignored(root string) bool {
	command := exec.Command("git", "check-ignore", "-q", ".")
	command.Dir = root
	command.Env = gitenv.Environ()
	return command.Run() == nil
}

func git(root string, arguments ...string) (string, error) {
	command := exec.Command("git", arguments...)
	command.Dir = root
	// See gitenv: GIT_DIR and its relatives outrank command.Dir, so without
	// the strip this would answer about whatever GIT_DIR names instead of the
	// tree the caller asked about.
	command.Env = gitenv.Environ()
	out, err := command.CombinedOutput()
	if err != nil {
		// git's own words go through: it is the only one that knows why it
		// could not answer.
		return "", fmt.Errorf("git %s in %s: %v: %s",
			strings.Join(arguments, " "), root, err, strings.TrimSpace(string(out)))
	}
	return string(out), nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/gitwork/ -v`
Expected: PASS, alle vier.

- [ ] **Step 5: Coverage prüfen**

Run: `go test ./internal/gitwork/ -coverprofile=cov.out`
Run: `go tool cover -func=cov.out`
Expected: 100 %. Kein plattformgebundener Zweig in diesem Paket, also kein Ausschluss.

- [ ] **Step 6: Commit**

```bash
git add internal/gitwork/
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 6: `internal/hostio` — die Adapternaht

**Files:**
- Create: `internal/hostio/hostio.go`
- Create: `internal/hostio/claude.go`
- Create: `internal/hostio/codex.go`
- Test: `internal/hostio/hostio_test.go`
- Test: `internal/hostio/claude_test.go`
- Test: `internal/hostio/codex_test.go`

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `type Host string` mit `HostClaude Host = "claude"`, `HostAntigravity Host = "antigravity"`, `HostCodex Host = "codex"`
  - `func ParseHost(s string) (Host, error)`
  - `type Payload struct { Event, SessionID string }`
  - `func Read(host Host, r io.Reader) (Payload, error)`
  - `func WriteContext(host Host, w io.Writer, lines []string) error`
  - `func FindRoot(start string) (string, error)`

`Payload` trägt vorerst nur `Event` und `SessionID`, weil `session-start` nur die beiden braucht. `Tool` und `Paths` kommen in Stufe 2 dazu, wenn das Subagent-Paar sie braucht — YAGNI, und ein Feld, das niemand liest, hat keinen Test, der es festhält.

- [ ] **Step 1: Write the failing test für Host und Wurzel**

`internal/hostio/hostio_test.go`:

```go
package hostio_test

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/xidus90/ultra-loom/internal/hostio"
)

func TestParseHost(t *testing.T) {
	for _, name := range []string{"claude", "antigravity", "codex"} {
		if _, err := hostio.ParseHost(name); err != nil {
			t.Errorf("ParseHost(%q): %v", name, err)
		}
	}
	// An unknown host is refused here rather than guessed at. The flag is
	// written by ulinit, so a value nobody knows means the two have drifted
	// apart, and answering a hook in the wrong shape is worse than refusing.
	if _, err := hostio.ParseHost("gemini-cli"); err == nil {
		t.Error("an unknown host is refused")
	}
	if _, err := hostio.ParseHost(""); err == nil {
		t.Error("an empty host is refused")
	}
}

// CLAUDE_PROJECT_DIR is never set by Antigravity, and its working directory is
// the one holding hooks.json -- `.agents/` -- so the root has to be found by
// walking up. Measured against MIGRATION.md:157.
func TestFindRootWalksUpToTheConfig(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".ultraloom"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".ultraloom", "config.toml"), []byte("[verify]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	deep := filepath.Join(root, ".agents")
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}

	got, err := hostio.FindRoot(deep)
	if err != nil {
		t.Fatal(err)
	}

	// EvalSymlinks on both sides: a temp directory on macOS is reached through
	// /var, which is a link to /private/var, and the comparison would fail on
	// the spelling rather than on the answer.
	want, _ := filepath.EvalSymlinks(root)
	gotResolved, _ := filepath.EvalSymlinks(got)
	if gotResolved != want {
		t.Fatalf("FindRoot = %q, want %q", gotResolved, want)
	}
}

func TestFindRootWithoutAConfig(t *testing.T) {
	_, err := hostio.FindRoot(t.TempDir())
	if !errors.Is(err, hostio.ErrNoRoot) {
		t.Fatalf("expected ErrNoRoot, got %v", err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/hostio/ -v`
Expected: FAIL — das Paket existiert nicht.

- [ ] **Step 3: Write hostio.go**

```go
// Package hostio is the seam between a hook's work and the host that calls it.
//
// One normalised payload in, one normalised answer out. The core packages see
// these two types and never a JSON envelope, so a second host costs an adapter
// and not a second copy of the hook.
//
// The host arrives as a flag and is not guessed from the payload. Guessing was
// the first design -- `tool_input.file_path` for Claude against `TargetFile`
// for Antigravity, the way `brain guard` does it -- and it cannot work here:
// the four events these hooks answer are not tool events at all. SessionStart,
// Stop and the subagent pair carry no `tool_input`, so there is nothing to
// recognise. The flag is not a second place for the same truth either, because
// ulinit writes both host files from one table and knows the host as it builds
// the command.
package hostio

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Host is which harness is calling.
type Host string

const (
	HostClaude      Host = "claude"
	HostAntigravity Host = "antigravity"
	HostCodex       Host = "codex"
)

// ErrNoRoot is returned when no `.ultraloom/config.toml` stands above the
// starting directory.
var ErrNoRoot = errors.New("no .ultraloom/config.toml above this directory")

// ParseHost turns the flag's value into a Host, or refuses it.
//
// Refused and not defaulted: the value is written by ulinit, so one nobody
// knows means the two have drifted apart. Answering a hook in the wrong shape
// is worse than refusing to answer.
func ParseHost(name string) (Host, error) {
	switch Host(name) {
	case HostClaude:
		return HostClaude, nil
	case HostAntigravity:
		return HostAntigravity, nil
	case HostCodex:
		return HostCodex, nil
	}
	return "", fmt.Errorf("unknown host %q: expected claude, antigravity or codex", name)
}

// Payload is what a hook needs to know, whichever host asked.
//
// Two fields, because session-start needs two. The tool and the paths a write
// barrier reads arrive when the stage that needs them does; a field nobody
// reads has no test holding it in place.
type Payload struct {
	Event     string
	SessionID string
}

// Read decodes the host's payload.
func Read(host Host, r io.Reader) (Payload, error) {
	switch host {
	case HostClaude:
		return readClaude(r)
	case HostAntigravity:
		return readAntigravity(r)
	case HostCodex:
		return readCodex(r)
	}
	return Payload{}, fmt.Errorf("unknown host %q", host)
}

// WriteContext hands lines back for the model to read.
func WriteContext(host Host, w io.Writer, lines []string) error {
	switch host {
	case HostClaude:
		return writeClaudeContext(w, lines)
	case HostAntigravity:
		return writeAntigravityContext(w, lines)
	case HostCodex:
		return writeCodexContext(w, lines)
	}
	return fmt.Errorf("unknown host %q", host)
}

// FindRoot walks up from `start` to the first directory holding
// `.ultraloom/config.toml`.
//
// Needed because `${CLAUDE_PROJECT_DIR}` is never set by Antigravity and its
// hooks run with the working directory set to the one holding `hooks.json`,
// which is `.agents/` (MIGRATION.md:157). A `--root` given on the command line
// outranks this and is handled by the caller.
func FindRoot(start string) (string, error) {
	current, err := filepath.Abs(start)
	if err != nil {
		return "", fmt.Errorf("resolving %s: %w", start, err)
	}
	for {
		candidate := filepath.Join(current, ".ultraloom", "config.toml")
		if _, err := os.Stat(candidate); err == nil {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", fmt.Errorf("%s: %w", start, ErrNoRoot)
		}
		current = parent
	}
}
```

- [ ] **Step 4: Write the failing test für den Claude-Adapter**

`internal/hostio/claude_test.go`:

```go
package hostio_test

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/hostio"
)

func TestReadClaude(t *testing.T) {
	body := `{"hook_event_name": "SessionStart", "session_id": "abc-123"}`

	got, err := hostio.Read(hostio.HostClaude, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}

	if got.Event != "SessionStart" || got.SessionID != "abc-123" {
		t.Fatalf("unexpected payload: %+v", got)
	}
}

// payload.py's rule: stdin that is not a JSON object is not a hook payload,
// and the refusal names why.
func TestReadClaudeRefusesWhatIsNotAPayload(t *testing.T) {
	for _, body := range []string{"", "not json", "[1, 2]", `"a string"`} {
		if _, err := hostio.Read(hostio.HostClaude, strings.NewReader(body)); err == nil {
			t.Errorf("expected a refusal for %q", body)
		}
	}
}

// A payload without a session id still reads: session_start.py records no base
// then and says nothing, because there is nowhere to file it. That decision
// lives in the hook, so the adapter must not refuse here.
func TestReadClaudeAcceptsAMissingSessionID(t *testing.T) {
	got, err := hostio.Read(hostio.HostClaude, strings.NewReader(`{"hook_event_name": "SessionStart"}`))
	if err != nil {
		t.Fatalf("a missing session id is the hook's business, not the adapter's: %v", err)
	}
	if got.SessionID != "" {
		t.Fatalf("expected an empty session id, got %q", got.SessionID)
	}
}

// Claude Code reads SessionStart context out of
// hookSpecificOutput.additionalContext. Plain stdout also reaches the
// transcript, but only the envelope reaches the model, so the envelope is what
// this writes.
func TestWriteClaudeContext(t *testing.T) {
	var out bytes.Buffer

	if err := hostio.WriteContext(hostio.HostClaude, &out, []string{"line one", "line two"}); err != nil {
		t.Fatal(err)
	}

	body := out.String()
	if !strings.Contains(body, `"hookEventName":"SessionStart"`) {
		t.Fatalf("the envelope names its event: %s", body)
	}
	if !strings.Contains(body, "line one\\nline two") {
		t.Fatalf("the lines arrive joined by a newline: %s", body)
	}
}

// Nothing to say is silence and not an empty envelope: an additionalContext of
// "" would put a blank line into every session's context.
func TestWriteClaudeContextOfNothingWritesNothing(t *testing.T) {
	var out bytes.Buffer

	if err := hostio.WriteContext(hostio.HostClaude, &out, nil); err != nil {
		t.Fatal(err)
	}

	if out.Len() != 0 {
		t.Fatalf("expected no output, got %q", out.String())
	}
}
```

- [ ] **Step 5: Run test to verify it fails**

Run: `go test ./internal/hostio/ -run Claude -v`
Expected: FAIL — `undefined: readClaude`

- [ ] **Step 6: Write claude.go**

```go
package hostio

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// claudePayload is the part of Claude Code's hook payload these hooks read.
type claudePayload struct {
	HookEventName string `json:"hook_event_name"`
	SessionID     string `json:"session_id"`
}

// readClaude is payload.py's `read`, narrowed to the fields in use.
//
// Anything that is not a JSON object is refused and named, which is that
// module's rule. A missing session id is not refused: session_start.py records
// no base commit then and stays silent about it, because there is nowhere to
// file one -- that decision belongs to the hook and not to this adapter.
func readClaude(r io.Reader) (Payload, error) {
	raw, err := io.ReadAll(r)
	if err != nil {
		return Payload{}, fmt.Errorf("reading stdin: %w", err)
	}
	var probe any
	if err := json.Unmarshal(raw, &probe); err != nil {
		return Payload{}, fmt.Errorf("stdin is not JSON: %w", err)
	}
	if _, ok := probe.(map[string]any); !ok {
		return Payload{}, fmt.Errorf("a hook payload is an object")
	}
	var payload claudePayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return Payload{}, fmt.Errorf("stdin is not a hook payload: %w", err)
	}
	return Payload{Event: payload.HookEventName, SessionID: payload.SessionID}, nil
}

// writeClaudeContext puts lines where the model will read them.
//
// The envelope and not plain stdout: stdout from a SessionStart hook reaches
// the transcript, while `hookSpecificOutput.additionalContext` is what reaches
// the model. Nothing to say writes nothing at all -- an additionalContext of
// "" would put a blank line into the context of every session.
func writeClaudeContext(w io.Writer, lines []string) error {
	if len(lines) == 0 {
		return nil
	}
	envelope := map[string]any{
		"hookSpecificOutput": map[string]any{
			"hookEventName":     "SessionStart",
			"additionalContext": strings.Join(lines, "\n"),
		},
	}
	body, err := json.Marshal(envelope)
	if err != nil {
		return fmt.Errorf("encoding the hook answer: %w", err)
	}
	if _, err := w.Write(append(body, '\n')); err != nil {
		return fmt.Errorf("writing the hook answer: %w", err)
	}
	return nil
}
```

- [ ] **Step 7: Write the failing test für die Codex- und Antigravity-Naht**

`internal/hostio/codex_test.go`:

```go
package hostio_test

import (
	"bytes"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/hostio"
)

// The seam, and the whole of it. Codex is not installed on the development
// machine and its hook contract could not be computed from here, so there is
// no adapter -- only the promise that an unanswerable host is refused rather
// than answered in a shape somebody guessed.
//
// Reading refuses, and so does writing: a hook that read nothing must not go
// on to report something.
func TestCodexFailsClosed(t *testing.T) {
	if _, err := hostio.Read(hostio.HostCodex, strings.NewReader(`{"session_id": "x"}`)); err == nil {
		t.Error("the codex seam refuses to read")
	}
	var out bytes.Buffer
	if err := hostio.WriteContext(hostio.HostCodex, &out, []string{"a"}); err == nil {
		t.Error("the codex seam refuses to write")
	}
	if out.Len() != 0 {
		t.Errorf("a refusal writes nothing, got %q", out.String())
	}
}

// Antigravity's Stop and PreInvocation payloads were recorded in Task 2 but
// the session-start path there waits on the answer to whether PreInvocation
// can write context at all. Until then this arm is a seam too, and it says so
// rather than pretending.
func TestAntigravitySessionStartIsNotBuiltYet(t *testing.T) {
	var out bytes.Buffer
	err := hostio.WriteContext(hostio.HostAntigravity, &out, []string{"a"})
	if err == nil {
		t.Fatal("the antigravity context path is not built yet and must say so")
	}
	if !strings.Contains(err.Error(), "PreInvocation") {
		t.Fatalf("the refusal names what is missing, got %v", err)
	}
}
```

- [ ] **Step 8: Run test to verify it fails**

Run: `go test ./internal/hostio/ -run "Codex|Antigravity" -v`
Expected: FAIL — `undefined: readCodex`

- [ ] **Step 9: Write codex.go**

```go
package hostio

import (
	"errors"
	"fmt"
	"io"
)

// ErrNoAdapter is returned by a host arm that exists as a promise and not as
// an implementation.
var ErrNoAdapter = errors.New("no adapter for this host")

// readCodex is the seam and not an adapter.
//
// Codex is not installed on the development machine, and its hook contract
// could not be computed from there: what is documented is that it has a
// `hooks/hooks.json` mechanism and "runs no session-start hook"
// (superpowers/6.3.0/docs/porting-to-a-new-harness.md:240-243, 788), and that
// same page warns that a hook *system* is not a session-start *event* -- one
// harness carried the string SessionStart in its binary as telemetry while
// firing only pre/post-tool and stop.
//
// So this refuses. A guessed adapter would look exactly like a working one,
// and ultra-brain has already paid for that shape once: on 2026-09-06 its
// barrier refused by contract while the host read nothing, and a probe file
// landed on disk with the refusal unread.
func readCodex(io.Reader) (Payload, error) {
	return Payload{}, fmt.Errorf("codex: %w -- its hook contract is unmeasured, see the design", ErrNoAdapter)
}

func writeCodexContext(io.Writer, []string) error {
	return fmt.Errorf("codex: %w -- its hook contract is unmeasured, see the design", ErrNoAdapter)
}

// readAntigravity reads what the host recorded in the Task 2 measurement.
// Kept beside the seam because the Stop path arrives with the stop gate; only
// the fields session-start needs are read here.
func readAntigravity(r io.Reader) (Payload, error) {
	// The same object-shaped payload Claude sends, with the event under a
	// different key. Confirmed against the payloads recorded in
	// testdata/hostio during the Task 2 measurement.
	return readClaude(r)
}

// writeAntigravityContext is the arm that waits on a measurement.
//
// Whether `PreInvocation` can write into the model's context at all is
// question 2 of the Task 2 probe. Until it is answered, a context writer here
// would be a guess, and the fallback if the answer is no is prose in
// GEMINI.md rather than a hook.
func writeAntigravityContext(io.Writer, []string) error {
	return fmt.Errorf("antigravity: whether PreInvocation can write context is unmeasured: %w", ErrNoAdapter)
}
```

Weicht die in Aufgabe 2 aufgezeichnete Nutzlast von Claudes Form ab, ist `readAntigravity` entsprechend zu schreiben statt weiterzuleiten — und der Kommentar dort zu korrigieren. Der Test dafür gehört dann in `codex_test.go` neben die anderen Nahtprüfungen und liest die abgelegte Datei aus `testdata/hostio/`.

- [ ] **Step 10: Run tests and check coverage**

Run: `go test ./internal/hostio/ -coverprofile=cov.out`
Run: `go tool cover -func=cov.out`
Expected: ok, 100 %. Die `unknown host`-Zweige in `Read` und `WriteContext` sind über `hostio.Read(hostio.Host("nonsense"), …)` zu erreichen — ein Test dafür gehört dazu, weil ein unerreichbarer Zweig sonst ein Ausschluss ohne Begründung wäre.

- [ ] **Step 11: Commit**

```bash
git add internal/hostio/
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 7: `ulguard hook session-start`

**Files:**
- Create: `cmd/guard/hook_session_start.go`
- Modify: `cmd/guard/main.go:15-80` (Verteilung)
- Modify: `cmd/init/run.go:810-813` (`hookEntries`)
- Test: `cmd/guard/hook_session_start_test.go`
- Test: `cmd/guard/main_test.go` (Verteilung)
- Test: `cmd/init/run_test.go` (der geschriebene Eintrag)

**Interfaces:**
- Consumes: `hostio.ParseHost`, `hostio.Read`, `hostio.WriteContext`, `hostio.FindRoot`, `hostio.ErrNoRoot`, `sessions.ReadState`, `sessions.WriteState`, `sessions.SessionState`, `journal.Pending`, `gitwork.HeadCommit`.
- Produces: `ulguard hook session-start --host <h> [--root <d>]`.

`RUN_DIR` (`.ultraloom/runs`) wird hier als Konstante in `hook_session_start.go` geführt, mit dem Verweis auf `worktree.py:24`. Ein eigenes Paket für eine Zeichenkette wäre zu viel; wenn Stufe 3 sie ein zweites Mal braucht, zieht sie nach `internal/gitwork` — dort steht sie beim Rest der Baumfragen.

- [ ] **Step 1: Write the failing test**

`cmd/guard/hook_session_start_test.go`:

```go
package main

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const waitingRun = `{"delta":{},"detail":"which colour?","effort":null,"input_hash":"h1","kind":"gate","node":"ask","outcome":"paused","seconds":0.1,"tokens":0,"tools":null}`

// One line per paused run, in run order, and the resume command spelled out --
// a paused run has an address but no voice, and this hook is where the id
// comes from.
func TestHookSessionStartReportsAPausedRun(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-b", waitingRun)
	writeRun(t, root, "run-a", waitingRun)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(
		strings.NewReader(`{"hook_event_name":"SessionStart","session_id":"s1"}`),
		&stdout, &stderr, root, "claude")

	if code != ExitOK {
		t.Fatalf("session-start never blocks, got exit %d (%s)", code, stderr.String())
	}
	context := additionalContext(t, stdout.Bytes())
	if !strings.Contains(context, "run run-a is waiting at ask: which colour?") {
		t.Fatalf("the paused run is named: %q", context)
	}
	if !strings.Contains(context, `ultraloom resume run-a --answer "your answer"`) {
		t.Fatalf("the answer command is spelled out: %q", context)
	}
	// Sorted by file name, as session_start.py's `sorted(glob)` is: two runs
	// reported in directory order would read differently on two machines.
	if strings.Index(context, "run-a") > strings.Index(context, "run-b") {
		t.Fatalf("runs come in name order: %q", context)
	}
}

// ASCII down to the placeholder. This line is printed to whatever console the
// harness hands over, and on Windows that is cp1252 by default: a single "…"
// there does not merely show up wrong, it raises and the hook dies with a code
// the exit protocol does not describe.
func TestHookSessionStartSaysNothingNonASCII(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-a", waitingRun)

	var stdout, stderr bytes.Buffer
	runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	for _, b := range stdout.Bytes() {
		if b > 0x7f {
			t.Fatalf("non-ASCII byte %#x in the answer: %q", b, stdout.String())
		}
	}
}

// Silence when nothing waits: no envelope at all, so no blank line lands in
// the context of every session in every checkout.
func TestHookSessionStartIsSilentWithNothingWaiting(t *testing.T) {
	root := project(t)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK || stdout.Len() != 0 {
		t.Fatalf("expected exit 0 and no output, got %d and %q", code, stdout.String())
	}
}

// The base commit is written here and nowhere else: by the time the first Stop
// fires, the turn has already run, and anything it committed would sit inside
// the baseline that is supposed to expose it.
func TestHookSessionStartRecordsTheBaseCommit(t *testing.T) {
	root := project(t)
	gitInit(t, root)

	var stdout, stderr bytes.Buffer
	runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	state := readStateForTest(t, root, "s1")
	if len(state.Base) != 40 {
		t.Fatalf("expected a full sha as the base, got %q", state.Base)
	}
}

// Silent in both failure cases, as _record_base is: without a session id there
// is nowhere to file it, and outside a repository there is nothing to file.
// Neither is a defect of the project, and neither is worth a line in every
// session of every checkout that is not a repository. The stop gate is where
// the absence matters and where it is said out loud.
func TestHookSessionStartRecordsNoBaseWithoutARepository(t *testing.T) {
	root := project(t)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK {
		t.Fatalf("a checkout that is not a repository is not a failure, got %d", code)
	}
	if stderr.Len() != 0 {
		t.Fatalf("and it is not worth a word, got %q", stderr.String())
	}
}

func TestHookSessionStartRecordsNoBaseWithoutASessionID(t *testing.T) {
	root := project(t)
	gitInit(t, root)

	var stdout, stderr bytes.Buffer
	runHookSessionStart(strings.NewReader(`{"hook_event_name":"SessionStart"}`), &stdout, &stderr, root, "claude")

	dir := filepath.Join(root, ".ultraloom", "hooks")
	if entries, err := os.ReadDir(dir); err == nil && len(entries) > 0 {
		t.Fatalf("no session id means nowhere to file it, got %d files", len(entries))
	}
}

// A damaged journal is named and not swallowed, and it does not hide the other
// runs behind it: one damaged file is a finding of its own, and hiding the rest
// would turn a small defect into a silent one.
func TestHookSessionStartNamesADamagedJournalAndCarriesOn(t *testing.T) {
	root := project(t)
	writeRun(t, root, "run-broken", "{not json")
	writeRun(t, root, "run-ok", waitingRun)

	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, root, "claude")

	if code != ExitOK {
		t.Fatalf("a damaged journal does not end a session, got %d", code)
	}
	if !strings.Contains(stderr.String(), "run-broken") {
		t.Fatalf("the damaged file is named: %q", stderr.String())
	}
	if !strings.Contains(additionalContext(t, stdout.Bytes()), "run-ok") {
		t.Fatalf("the other runs are still reported: %q", stdout.String())
	}
}

// payload.py's exit protocol: 1 for an internal failure, and never 2 -- this
// hook is an announcement and has nothing to block.
func TestHookSessionStartOnABadPayload(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader("{not json"), &stdout, &stderr, project(t), "claude")

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if strings.TrimSpace(stderr.String()) == "" {
		t.Fatal("a refusal says why")
	}
}

func TestHookSessionStartOnAnUnknownHost(t *testing.T) {
	var stdout, stderr bytes.Buffer
	code := runHookSessionStart(strings.NewReader(`{"session_id":"s1"}`), &stdout, &stderr, project(t), "gemini-cli")

	if code != ExitInternal {
		t.Fatalf("an unknown host is refused, got %d", code)
	}
}

func project(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".ultraloom"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".ultraloom", "config.toml"), []byte("[verify]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func writeRun(t *testing.T, root, runID, body string) {
	t.Helper()
	dir := filepath.Join(root, ".ultraloom", "runs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, runID+".jsonl"), []byte(body+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func gitInit(t *testing.T, root string) {
	t.Helper()
	for _, args := range [][]string{
		{"init"},
		{"config", "user.email", "t@example.invalid"},
		{"config", "user.name", "Test"},
	} {
		command := exec.Command("git", args...)
		command.Dir = root
		if out, err := command.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"add", "a.txt"}, {"commit", "-m", "first"}} {
		command := exec.Command("git", args...)
		command.Dir = root
		if out, err := command.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
}

func additionalContext(t *testing.T, body []byte) string {
	t.Helper()
	var envelope struct {
		HookSpecificOutput struct {
			AdditionalContext string `json:"additionalContext"`
		} `json:"hookSpecificOutput"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("the answer is not an envelope: %s", body)
	}
	return envelope.HookSpecificOutput.AdditionalContext
}
```

Dazu der Helfer in derselben Datei:

```go
// Through the package under test's own door rather than by parsing the file
// again: a second reader here would pass while ReadState was broken.
func readStateForTest(t *testing.T, root, sessionID string) sessions.SessionState {
	t.Helper()
	return sessions.ReadState(root, sessionID)
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/guard/ -run TestHookSessionStart -v`
Expected: FAIL — `undefined: runHookSessionStart`

- [ ] **Step 3: Write the implementation**

`cmd/guard/hook_session_start.go`:

```go
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/xidus90/ultra-loom/internal/gitwork"
	"github.com/xidus90/ultra-loom/internal/hostio"
	"github.com/xidus90/ultra-loom/internal/journal"
	"github.com/xidus90/ultra-loom/internal/sessions"
)

// runDir is worktree.py:24's RUN_DIR. Spelled here because one caller needs
// it; when the stop gate needs it too it moves to internal/gitwork, where the
// rest of the tree questions live.
const runDir = ".ultraloom/runs"

// runHookSessionStart tells a fresh session which runs are still waiting for
// an answer, and writes down the commit the session starts on.
//
// Never blocks. This is an announcement, so the only codes it can leave with
// are 0 and 1 -- exit 2 would hold a turn over a report.
func runHookSessionStart(stdin io.Reader, stdout, stderr io.Writer, root, hostName string) int {
	host, err := hostio.ParseHost(hostName)
	if err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}
	payload, err := hostio.Read(host, stdin)
	if err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}

	recordBase(payload.SessionID, root)

	lines := waiting(root, stderr)
	if err := hostio.WriteContext(host, stdout, lines); err != nil {
		fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
		return ExitInternal
	}
	return ExitOK
}

// recordBase keeps the commit this session starts on, if there is one to keep.
//
// Here and nowhere else: by the time the first Stop fires, the turn has
// already run, and anything it committed would sit inside the baseline that is
// supposed to expose it.
//
// Silent in both failure cases, which is _record_base's decision. Without a
// session id there is nowhere to file it, and outside a repository there is
// nothing to file -- neither is a defect of the project, and neither is worth
// a line in every session of every checkout that is not a git repository. The
// stop gate is where the absence matters, and that is where it is said out
// loud.
func recordBase(sessionID, root string) {
	if sessionID == "" {
		return
	}
	commit, err := gitwork.HeadCommit(root)
	if err != nil {
		return
	}
	state := sessions.ReadState(root, sessionID)
	state.Base = commit
	// A write that fails is silent for the same reason the two refusals above
	// are: the gate reads an absent base and says so itself.
	_ = sessions.WriteState(root, sessionID, state)
}

// waiting is one line per paused run, in run order.
func waiting(root string, stderr io.Writer) []string {
	dir := filepath.Join(root, filepath.FromSlash(runDir))
	entries, err := os.ReadDir(dir)
	if err != nil {
		// No runs directory means no runs. Not a finding.
		return nil
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".jsonl") {
			names = append(names, entry.Name())
		}
	}
	// By name, as session_start.py's `sorted(glob(...))` is: two runs reported
	// in directory order would read differently on two machines.
	sort.Strings(names)

	var lines []string
	for _, name := range names {
		path := filepath.Join(dir, name)
		gate, err := journal.Pending(path)
		if err != nil {
			// Named, not swallowed, and not fatal either: one damaged file is
			// a finding of its own, and hiding the other runs behind it would
			// turn a small defect into a silent one.
			fmt.Fprintf(stderr, "ulguard hook session-start: %v\n", err)
			continue
		}
		if gate == nil {
			continue
		}
		runID := strings.TrimSuffix(name, ".jsonl")
		// ASCII on purpose, down to the placeholder: this line reaches
		// whatever console the harness hands over, and on Windows that is
		// cp1252 by default. A single "..." spelled as one rune there does not
		// merely show up wrong -- the write fails, and the hook dies with a
		// code the exit protocol does not describe.
		lines = append(lines, fmt.Sprintf(
			"run %s is waiting at %s: %s\n  answer it with: ultraloom resume %s --answer \"your answer\"",
			runID, gate.Node, gate.Question, runID))
	}
	return lines
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./cmd/guard/ -run TestHookSessionStart -v`
Expected: PASS, alle neun.

- [ ] **Step 5: Verteilung in `main.go` erweitern — Test zuerst**

In `cmd/guard/main_test.go` anfügen:

```go
// `hook <event>` is a two-word subcommand, unlike the six single-word ones
// beside it, so a mistyped event must not fall through to the write barrier:
// the barrier reads stdin and decides about a file, and answering a hook call
// that way would be a verdict about the wrong question.
func TestCLIRefusesAnUnknownHookEvent(t *testing.T) {
	var stderr bytes.Buffer
	code := cli([]string{"hook", "no-such-event"}, strings.NewReader(""), &stderr)

	if code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
	if !strings.Contains(stderr.String(), "no-such-event") {
		t.Fatalf("the refusal names the event, got %q", stderr.String())
	}
}

func TestCLIRefusesHookWithoutAnEvent(t *testing.T) {
	var stderr bytes.Buffer
	if code := cli([]string{"hook"}, strings.NewReader(""), &stderr); code != ExitInternal {
		t.Fatalf("expected exit 1, got %d", code)
	}
}
```

Run: `go test ./cmd/guard/ -run TestCLIRefuses -v`
Expected: FAIL — die Verteilung kennt `hook` nicht und fällt auf die Schranke durch, die Exit 2 oder 0 gibt.

- [ ] **Step 6: Verteilung schreiben**

In `cmd/guard/main.go`, vor dem abschließenden Schranken-Block:

```go
	// `hook` carries a second word, unlike every subcommand above. A mistyped
	// event is refused here rather than falling through to the write barrier
	// below: that barrier reads stdin and decides about a file, and answering
	// a hook call that way is a verdict about the wrong question.
	if len(args) > 0 && args[0] == "hook" {
		if len(args) < 2 {
			fmt.Fprintln(stderr, "usage: ulguard hook <event> --host <host> [--root <dir>]")
			return ExitInternal
		}
		event := args[1]
		flags := flag.NewFlagSet("ultraloom-guard hook "+event, flag.ContinueOnError)
		flags.SetOutput(stderr)
		root := flags.String("root", "", "path to the project root")
		host := flags.String("host", "claude", "the harness calling: claude, antigravity or codex")
		if err := flags.Parse(args[2:]); err != nil {
			return ExitInternal
		}
		// An empty --root is the Antigravity case: the variable
		// ${CLAUDE_PROJECT_DIR} is never set there and the working directory
		// is the one holding hooks.json, so the root is found by walking up.
		resolved := *root
		if resolved == "" {
			found, err := hostio.FindRoot(".")
			if err != nil {
				fmt.Fprintf(stderr, "ultraloom-guard hook %s: %v\n", event, err)
				return ExitInternal
			}
			resolved = found
		}
		switch event {
		case "session-start":
			return runHookSessionStart(stdin, os.Stdout, stderr, resolved, *host)
		}
		fmt.Fprintf(stderr, "ultraloom-guard hook: unknown event %q\n", event)
		return ExitInternal
	}
```

Run: `go test ./cmd/guard/`
Expected: ok

- [ ] **Step 7: `ulinit` schreibt den Eintrag — Test zuerst**

In `cmd/init/run_test.go` anfügen:

```go
// The generated SessionStart entry names the Go binary and the host. The
// Python entry point it replaces stays in pyproject.toml for the agent flow,
// so both names exist and only the one written here decides which runs.
func TestHookEntriesSessionStartIsTheGoBinary(t *testing.T) {
	entries := hookEntries(detect.Facts{HasGit: true}, false)

	var found string
	for _, entry := range entries {
		if entry.Event == "SessionStart" {
			found = entry.Command
		}
	}
	if !strings.Contains(found, "ulguard hook session-start") {
		t.Fatalf("SessionStart runs the Go binary, got %q", found)
	}
	if !strings.Contains(found, "--host claude") {
		t.Fatalf("and it names the host, got %q", found)
	}
}
```

Run: `go test ./cmd/init/ -run TestHookEntriesSessionStart -v`
Expected: FAIL — der Eintrag lautet noch `ultraloom hook session-start --root …`

- [ ] **Step 8: `hookEntries` ändern**

In `cmd/init/run.go`:

```go
// guardHookCommand builds what a generated hook runs on Claude Code: the Go
// binary by name, the event, and the host it is answering.
//
// By name for the reason hookCommand records: a name has no directory that a
// working tree could be missing. The host is a flag because these events carry
// no `tool_input` to recognise one from -- see internal/hostio.
func guardHookCommand(event string) string {
	return `ulguard hook ` + event + ` --host claude --root "${CLAUDE_PROJECT_DIR}"`
}
```

und in `hookEntries` die SessionStart-Zeile:

```go
		{Event: "SessionStart", Command: guardHookCommand("session-start"), Timeout: 20},
```

`hookCommand` bleibt stehen — die drei übrigen Ereignisse laufen bis zu ihren Stufen weiter über Python.

Run: `go test ./cmd/init/`
Expected: ok. Schlägt ein vorhandener Test auf den alten Text an, ist er mit anzupassen: der Eintrag hat sich absichtlich geändert.

- [ ] **Step 9: Ganzen Baum prüfen**

Run: `gofmt -l cmd internal`
Expected: keine Ausgabe

Run: `go vet ./...`
Expected: keine Ausgabe

Run: `go test ./... -coverprofile=cov.out`
Expected: ok für jedes Paket

Run: `go tool cover -func=cov.out | tail -1`
Expected: mindestens 98,0 %

- [ ] **Step 10: Am echten Hook messen, nicht nur im Test**

Bauen und gegen eine Nutzlast laufen lassen, wie der Host sie schickt:

```bash
go build -o /c/Users/micro/go/bin/ulguard.exe ./cmd/guard
```

```bash
echo '{"hook_event_name":"SessionStart","session_id":"probe-1"}' | ulguard hook session-start --host claude --root .
```

Expected: Exit 0. Steht ein Lauf im Journal, kommt die Hülle mit `additionalContext`; steht keiner, kommt nichts. Prüfen, dass `.ultraloom/hooks/probe-1.json` danach einen 40-stelligen `base` trägt:

```bash
cat .ultraloom/hooks/probe-1.json
```

Und dass die Python-Seite dieselbe Datei noch lesen kann — beide Fassungen laufen bis Stufe 5 nebeneinander:

```bash
uv run --project . python -c "from pathlib import Path; from ultraloom.hooks.state import read; print(read(Path('.'), 'probe-1'))"
```

Expected: ein `SessionState` mit gesetztem `base`, kein leeres. Kommt ein leeres zurück, hält die Datei die Form nicht und Aufgabe 3 ist nicht fertig.

- [ ] **Step 11: `ulinit` laufen lassen und den Eintrag ansehen**

```bash
ulinit --yes
```

```bash
git diff .claude/settings.json
```

Expected: der SessionStart-Eintrag steht auf `ulguard hook session-start --host claude --root "${CLAUDE_PROJECT_DIR}"`, `ultraLoomOwned` bleibt, und **kein** zweiter SessionStart-Eintrag ist entstanden. Ein zweiter heißt, dass `toolKey` aus Aufgabe 1 nicht greift.

- [ ] **Step 12: Commit**

```bash
git add cmd/guard/hook_session_start.go cmd/guard/hook_session_start_test.go cmd/guard/main.go cmd/guard/main_test.go cmd/init/run.go cmd/init/run_test.go .claude/settings.json
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

### Task 8: Den Python-Hook fallen lassen

Erst jetzt, und nur für dieses eine Ereignis. Die Reihenfolge ist die Regel des Spec: der Go-Hook steht und ist grün, dann schaltet `ulinit` um, dann fällt der Python-Hook. Nie umgekehrt.

**Files:**
- Delete: `src/ultraloom/hooks/session_start.py`
- Delete: `tests/hooks/test_session_start.py`
- Modify: `src/ultraloom/cli.py:194` (der Unterbefehl)
- Modify: `src/ultraloom/hooks/cli.py:9` (der Import)
- Modify: `tests/test_cli.py` (die Fälle zu `hook session-start`)
- Modify: `tests/test_module_boundary.py` (falls es das Modul nennt)

**Interfaces:**
- Consumes: nichts.
- Produces: nichts. `ultraloom hook session-start` gibt es danach nicht mehr.

- [ ] **Step 1: Nachsehen, wer das Modul nennt**

```bash
grep -rn "session_start" --include='*.py' --include='*.toml' src tests
```

Jeder Treffer wird in diesem Schritt gelesen, nicht überflogen: `tests/test_module_boundary.py` prüft Importregeln über Module, die hier verschwinden, und ein Test, der die Abwesenheit eines Moduls prüft, muss gegen die neue Wahrheit gestellt werden statt gelöscht.

- [ ] **Step 2: Den Test zuerst ändern**

In `tests/test_cli.py` die Fälle, die `hook session-start` aufrufen, in einen Fall umschreiben, der belegt, dass es den Unterbefehl **nicht** mehr gibt:

```python
def test_hook_session_start_is_gone(capsys: pytest.CaptureFixture[str]) -> None:
    """The Go binary answers SessionStart now; two entry points would drift.

    Written as a test and not just as a deletion, because a subcommand that
    quietly comes back is how the two halves start disagreeing about which one
    the host calls.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["hook", "session-start", "--root", "."])
    assert exit_info.value.code != 0
```

Run: `uv run pytest tests/test_cli.py::test_hook_session_start_is_gone -v`
Expected: FAIL — der Unterbefehl ist noch da und antwortet mit 0.

- [ ] **Step 3: Löschen und den Parser kürzen**

```bash
git rm src/ultraloom/hooks/session_start.py tests/hooks/test_session_start.py
```

In `src/ultraloom/cli.py` die Zeile `hook_subs.add_parser("session-start", …)` entfernen, in `src/ultraloom/hooks/cli.py` den Import `from ultraloom.hooks import session_start` und den zugehörigen Zweig.

- [ ] **Step 4: Tests laufen lassen**

Run: `uv run pytest tests/ -q`
Expected: alles grün. Bricht ein Import, ist ein Nenner aus Schritt 1 übersehen worden.

- [ ] **Step 5: Coverage prüfen**

Run: `uv run coverage run -m pytest tests/ -q`
Run: `uv run coverage report`
Expected: 100 %. Fällt die Zahl, hat eine gelöschte Testdatei Zeilen mitgedeckt, die ein anderes Modul braucht — dann fehlt dort ein Test, und der wird geschrieben, nicht ausgeschlossen.

- [ ] **Step 6: Ganzes Gate laufen lassen**

Run: `ulguard status`
Expected: der SessionStart-Eintrag ist als installiert gemeldet.

Run: `uv run --project . ultraloom check all`
Expected: jede Lane grün.

- [ ] **Step 7: Commit**

```bash
git add -A src/ultraloom tests
```
```bash
git diff --cached --stat
```
```bash
git commit -F commitmsg.txt
```

---

## Was dieser Plan nicht enthält

- **Antigravity-`session-start`.** Wartet auf Frage 2 aus Aufgabe 2. Der Adapterarm verweigert bis dahin und sagt, was fehlt.
- **Codex, überhaupt.** Naht mit einem Test, mehr wäre geraten.
- **Stufe 2 bis 5.** `internal/child` (der Prozessbaum), `internal/lanes`, `internal/ulconfig`, das Stop-Gate, `ulguard check all` und der Schnitt. Eigene Pläne, und Stufe 3 lässt sich erst planen, wenn Aufgabe 2 die Zeitgrenze kennt.
- **Der zweite Schreiber für `.agents/hooks.json`.** Gehört zu dem Ereignis, das dort zuerst ankommt — und das ist keines aus diesem Plan.
- **Golden-Dateien für die zwei Antwortformen.** Das Spec verlangt sie, und sie sind hier nicht zu bauen: die zweite Form ist Antigravitys, und deren Schreibarm ist in Aufgabe 6 eine Naht. Eine Golden-Datei über *eine* Form fängt keinen Formatwechsel, sie schreibt nur fest, was `claude_test.go` schon prüft. Sie gehört in den Plan, der den Antigravity-Arm baut, und der Vorrat dafür entsteht in Aufgabe 2 unter `testdata/hostio/`.

## Abweichungen vom Spec

Zwei, beide begründet und beide in das Spec nachzutragen, wenn der Plan angenommen wird:

1. **Der Sitzungszustand geht nach `internal/sessions`, nicht nach `internal/journal`.** Das Spec zählt `journal.py`, `gate.py` und `state.py` gemeinsam als `internal/journal`. `internal/sessions` hält aber `StateDir` und `safeName` bereits, und `safeName` trägt die gegen `state.py` nachgerechnete Unicode-Regel samt Messung vom 2026-09-07. Zwei Pakete hätten zwei Namensregeln für eine Datei.
2. **`session_start.py` fällt in Aufgabe 8 und nicht erst in Stufe 5.** Das Spec listet die Löschungen unter Stufe 5, sagt aber in derselben Abteilung die Reihenfolge innerhalb jeder Stufe: Go-Hook grün, dann `ulinit`, dann der Python-Hook. Aufgabe 8 ist diese Reihenfolge für ein Ereignis; Stufe 5 behält, was dann noch steht.
