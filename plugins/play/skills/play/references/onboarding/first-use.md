# First-use Play orientation

Use this guidance only after an empty `$play` or `/play` invocation has live-verified an installed,
authenticated Rote identity. Keep canonical URI onboarding separate.

## Promise

Lead with: **Get the result. Keep the method.**

Explain these facts in plain language:

- A Play is a job that has been worked out, checked, and saved.
- Rote checks and runs Plays on the user's computer.
- Play searches for an existing method before starting new exploration.
- If none fits, the human and agent work out the job together.
- The agent brings broad knowledge, search, tool use, and testing.
- The human is the domain expert because only they know the local goals, rules, exceptions,
  standards, history, and judgment that make the result right.
- The human can watch, correct, steer, and approve the work.
- A successful repeatable method becomes a Play only when the human chooses to save it.
- The human may keep it private, share it with an authorized team, or publish it for the community.
- Credentials remain local and nothing runs before the exact inspected work is approved.

Do not use `adapter`, `crystallize`, `inference substrate`, `workflow artifact`, or other machinery
in the first-use explanation. Do not imply that raw conversation, credentials, or unchosen private
knowledge becomes memory.

## Typed choices

After the orientation is presented and remembered, offer:

1. **Try Hello** — inspect `modiqo/hello@0.1.0`, then ask whether to run it.
2. **Tell me your goal** — accept ordinary language and route it through normal Play invocation.
3. **See useful Plays** — open the normal remembered awareness inbox.
4. **Not now** — finish without inspection or execution.

The starter choice authorizes read-only inspection only. Preserve the normal disclosure and
`approve_play_run` gate. Pin the exact starter version; replacing it requires a deliberate source
change and tests.

After a verified starter receipt, explain what happened without replacing or summarizing the full
result. Offer a goal, useful Plays, or Finish.

## Owner-private memory

Use `~/.rote/play/onboarding-state.json` only for first-use orientation memory. Store:

- a SHA-256 digest of the authenticated email;
- the orientation version;
- the UTC time when the orientation was presented.

Use user-only directory and file permissions. Store no email, request, prompt, Play result,
credential, raw `whoami` output, or controller context. Treat a missing entry as first use, the
current version as returning, and malformed state as a blocker. Record the marker only after the
presentation event succeeds. Keep first orientation and first verified Play activation separate.
