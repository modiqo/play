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
event, reference, parameters, or creator intent. After inspection, an exact local Play proceeds
without a pull prompt. `approve_play_run` is mandatory when inspection reports that a remote Play
must be installed, replaced, or repaired; the original request never supplies that pull consent.
Always show the inspection disclosure before asking that question. Never skip authentication,
effect, modality widening, remote pull, or publication visibility gates.
