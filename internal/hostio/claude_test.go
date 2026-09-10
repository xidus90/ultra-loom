package hostio_test

import (
	"bytes"
	"errors"
	"strings"
	"testing"

	"github.com/xidus90/ultra-loom/internal/hostio"
)

// brokenReader and brokenWriter stand for a stdin that dies mid-read and a
// stdout that is closed: both are real for a hook whose host goes away, and
// neither can be produced by a string or a buffer.
type brokenReader struct{ err error }

func (b brokenReader) Read([]byte) (int, error) { return 0, b.err }

type brokenWriter struct{ err error }

func (b brokenWriter) Write([]byte) (int, error) { return 0, b.err }

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
// and the refusal names why. Checked against src/ultraloom/hooks/payload.py --
// it raises "stdin is not JSON: ..." and "a hook payload is an object", and
// those two are told apart here as well.
func TestReadClaudeRefusesWhatIsNotAPayload(t *testing.T) {
	for _, testCase := range []struct {
		body   string
		reason string
	}{
		{"", "stdin is not JSON"},
		{"not json", "stdin is not JSON"},
		{"[1, 2]", "a hook payload is an object"},
		{`"a string"`, "a hook payload is an object"},
		// An object whose field has the wrong type gets past the probe above
		// and is refused by the decode into the payload's own shape.
		{`{"session_id": 5}`, "stdin is not a hook payload"},
	} {
		_, err := hostio.Read(hostio.HostClaude, strings.NewReader(testCase.body))
		if err == nil {
			t.Errorf("expected a refusal for %q", testCase.body)
			continue
		}
		if !strings.Contains(err.Error(), testCase.reason) {
			t.Errorf("refusal for %q was %v, want it to name %q", testCase.body, err, testCase.reason)
		}
	}
}

// A stdin that fails mid-read is not a malformed payload, and the refusal says
// which of the two happened.
func TestReadClaudeReportsAFailingStdin(t *testing.T) {
	boom := errors.New("pipe closed")

	_, err := hostio.Read(hostio.HostClaude, brokenReader{err: boom})

	if !errors.Is(err, boom) {
		t.Fatalf("expected the reader's error, got %v", err)
	}
	if !strings.Contains(err.Error(), "reading stdin") {
		t.Fatalf("the refusal names what failed, got %v", err)
	}
}

// A payload without a session id still reads: session_start.py records no base
// then and says nothing, because there is nowhere to file it. That decision
// lives in the hook, so the adapter must not refuse here. Checked against
// _record_base in src/ultraloom/hooks/session_start.py.
func TestReadClaudeAcceptsAMissingSessionID(t *testing.T) {
	got, err := hostio.Read(hostio.HostClaude, strings.NewReader(`{"hook_event_name": "SessionStart"}`))
	if err != nil {
		t.Fatalf("a missing session id is the hook's business, not the adapter's: %v", err)
	}
	if got.SessionID != "" {
		t.Fatalf("expected an empty session id, got %q", got.SessionID)
	}
}

// hookSpecificOutput.additionalContext is the field Claude Code documents for
// SessionStart context, so that is the field this writes. What plain stdout
// does instead could not be measured from here and is not claimed.
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

// A line is prose and not HTML: a greater-than sign in a context line has to
// arrive as itself and not as the unicode escape the encoder writes for it
// unless it is told otherwise.
func TestWriteClaudeContextLeavesProseAlone(t *testing.T) {
	var out bytes.Buffer

	if err := hostio.WriteContext(hostio.HostClaude, &out, []string{"run 7 > gate open"}); err != nil {
		t.Fatal(err)
	}

	if !strings.Contains(out.String(), "run 7 > gate open") {
		t.Fatalf("expected the line unescaped: %s", out.String())
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

func TestWriteClaudeContextReportsAFailingStdout(t *testing.T) {
	boom := errors.New("stdout closed")

	err := hostio.WriteContext(hostio.HostClaude, brokenWriter{err: boom}, []string{"a"})

	if !errors.Is(err, boom) {
		t.Fatalf("expected the writer's error, got %v", err)
	}
}

// The switch refuses a Host nobody parsed rather than falling through to one
// of the arms. Reachable only from inside the package's own type, which is
// exactly why it is tested: an unreachable branch would be an exclusion
// without a reason.
func TestAnUnparsedHostIsRefused(t *testing.T) {
	if _, err := hostio.Read(hostio.Host("nonsense"), strings.NewReader("{}")); err == nil {
		t.Error("Read refuses a host it does not know")
	}
	var out bytes.Buffer
	if err := hostio.WriteContext(hostio.Host("nonsense"), &out, []string{"a"}); err == nil {
		t.Error("WriteContext refuses a host it does not know")
	}
	if out.Len() != 0 {
		t.Errorf("a refusal writes nothing, got %q", out.String())
	}
}
