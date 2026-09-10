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

// claudeAnswer is the envelope Claude Code reads a SessionStart answer from.
type claudeAnswer struct {
	HookSpecificOutput struct {
		HookEventName     string `json:"hookEventName"`
		AdditionalContext string `json:"additionalContext"`
	} `json:"hookSpecificOutput"`
}

// readClaude is payload.py's `read`, narrowed to the fields in use.
//
// Anything that is not a JSON object is refused and named, which is that
// module's rule. The probe into `any` and the decode into claudePayload are
// two passes on purpose: payload.py tells "stdin is not JSON" apart from "a
// hook payload is an object", and a single decode into a map would merge the
// two refusals into whichever one the decoder happened to phrase.
//
// A missing session id is not refused: session_start.py's `_record_base`
// returns without a word when the id is not a string, because there is nowhere
// to file a base commit -- that decision belongs to the hook and not to this
// adapter.
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
// `hookSpecificOutput.additionalContext` is the field Claude Code documents
// for a SessionStart hook's context, and the field the superpowers port table
// names for this harness (superpowers/6.3.0/docs/porting-to-a-new-harness.md,
// harness table at :788). What plain stdout from such a hook does instead
// could not be measured from inside this repository, so nothing is claimed
// about it here.
//
// Nothing to say writes nothing at all -- an additionalContext of "" would put
// a blank line into the context of every session.
//
// The encoder writes straight into w and its escaping is turned off: a context
// line is prose, and a `>` in it belongs in the transcript as itself. The only
// failure it can report is w's, because the document holds nothing but
// strings.
func writeClaudeContext(w io.Writer, lines []string) error {
	if len(lines) == 0 {
		return nil
	}
	var answer claudeAnswer
	answer.HookSpecificOutput.HookEventName = "SessionStart"
	answer.HookSpecificOutput.AdditionalContext = strings.Join(lines, "\n")

	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(answer); err != nil {
		return fmt.Errorf("writing the hook answer: %w", err)
	}
	return nil
}
