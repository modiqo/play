---
name: play
description: >
  Sidekick for reusable procedures. When the user asks for an outcome, Play checks whether a saved
  Play already does it and offers to run it; after complicated repeatable work, Play offers to save
  it. Otherwise it stays out of the way. Also handles explicit Play requests: onboarding, canonical
  Play URIs, digest, management, and sharing.
---

# Play

Play's typed runtime owns all control flow. Your job at each yield is small and local; never read
the machine, actions, prompts, or references to reconstruct it.

## Enter

```text
play-machine run-until-yield --stdin --json
```

with `{"run_id":"<run-id>","task_key":"<task-key>","request":{"original":"<request>"}}`.

The runtime returns a projection and a short `continuation_id`. Keep the ID opaque; resume with
`{"continuation_id":"<id>","event":{"id":"<event>","payload":{}}}`. If `play-machine` is missing,
report that Play installation is incomplete and stop.

## Handle the yield

The projection is the entire contract for the current moment. Act on `projection.state.boundary`:

- `model` — reason over `instruction.input` only; return one declared event with its required
  payload fields.
- `human` — present the projected prompt verbatim through structured elicitation; resume with the
  selected event.
- `specialist` — invoke exactly `instruction.specialist` with `instruction.input`; resume with the
  one accepted receipt event.
- `terminal` — present the terminal presentation and stop.

Pass any returned `presentations` to the user in order, then handle the boundary. Do not narrate
deterministic transitions, print continuation IDs, or summarize raw payloads the projection marks
as complete results.

## Stay out of the way

If qualification returns `conversation` or `play_excluded`, Play exits silently. When no adequate
Play exists, classify the fallback before work as `capture` or `normal`. Capture creates and binds a
Rote workspace; normal creates no trajectory. Re-enter only with the explicit capture handle after
that Rote trajectory verifies. A post-hoc `task_settled` event is invalid. Saving,
publication, and sharing run through the projected specialist handoffs — never through manual
registry, adapter, or filesystem work.

## Fail closed

Stop with the projected blocker on: an undeclared event, invalid payload, continuation or bundle
mismatch, unavailable specialist, declined approval, or unverifiable outcome. Never infer success
from specialist prose, and never present a save or publication as complete without the runtime's
receipt.
