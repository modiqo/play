# Cross-Harness Elicitation

Treat every finite decision as one declarative prompt from `references/controller/prompts.yaml`.
The prompt id, selection mode, choices, events, and required payload are invariant across harnesses.

## Native surface

- Codex: use `request_user_input` when available.
- Claude: use `askquestion` or its native structured-question equivalent.
- Kimi: use `askquestion` or its native structured-question equivalent.
- Other harnesses: use their structured elicitation control when available.

Use `scripts/lib/play/elicitation.py` to validate and translate the common question contract. Tool
availability is owned by the harness; never claim a control exists when it is absent.

Use `scripts/bin/play-question <prompt-id> --harness <codex|claude|kimi>` to inspect the exact
native payload, or add `--format markdown` to verify the fallback.

## Fallback

When no native structured control exists, render the same choices as a numbered Markdown list.
Ask for one number for single-select or comma-separated numbers for multi-select. Accept only a
declared event and payload.

Skip redundant elicitation when the user's explicit request already supplies the exact declared
event, reference, parameters, or creator intent, except for `approve_play_run`. A request containing
“run” selects the candidate and parameters to inspect; it never supplies post-inspection approval.
Always show the inspection disclosure before asking that question. Never skip authentication,
effect, modality widening, execution, or publication visibility gates.
