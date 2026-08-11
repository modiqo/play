---
name: play
description: >
  Sidekick for reusable procedures. When the user asks for an outcome, Play checks whether a saved
  Play already does it and offers to run it; after complicated repeatable work settles, Play offers
  to save it. Otherwise it stays out of the way. Also handles explicit Play requests: onboarding,
  canonical Play URIs, digest, management, sharing, and birth certificates.
---

# Play

Play's typed runtime owns all control flow. Your job at each yield is small and local. Never read
`machine.yaml`, `actions.yaml`, `prompts.yaml`, schemas, or reference files during a run — the
returned projection is the entire instruction contract for the current moment.

## Enter or resume

For a new task run `play-machine run-until-yield --stdin --json` with a harness-owned run ID,
stable task key, and the unchanged user request:

```json
{"run_id":"<run-id>","task_key":"<task-key>","request":{"original":"<request>"}}
```

The installer places `play-machine` on `PATH`; if it is unavailable, report that Play installation
is incomplete and stop. An explicit `/play` or `$play` with no separate task is a complete
onboarding request: set `request.original` to `/play`. After a task Play stepped aside from
settles, re-enter once with `request.original` set to `$play settle <one-line summary>`.

The command executes every eligible deterministic action and stops only at a model, human,
specialist, or terminal boundary, returning a short `continuation_id`. Keep that value opaque in
harness state — never inspect, print, or persist it yourself. The runtime stores context
owner-privately under `~/.rote-play/continuations` and expires it after 24 hours. Resume with:

```json
{"continuation_id":"<24-character-id>","event":{"id":"<event>","payload":{},"guards":{}}}
```

## Handle the yield

Present returned `presentations` in order, then act on `projection.state.boundary`:

- `model`: reason over only `instruction.input` and the projected policy; return one declared
  event with every required payload field.
- `human`: present the exact projected prompt through structured elicitation; resume with the
  selected declared event.
- `specialist`: invoke only `instruction.specialist` with `instruction.input` through the
  harness's skill mechanism; resume with the one accepted typed receipt event. Interactive
  specialists own their own user questions — ask those directly and continue inside the
  specialist flow; return to the runtime only with a declared receipt event.
- `terminal`: present the terminal outcome and stop.

If `instruction.preflight_required_for_events` names your selected event, run
`play-machine preflight --harness <codex|claude|generic> --json` first and pass its complete
unchanged output as `preflight`. Missing Rote setup delegates to the `rote-setup` skill.

## Stay out of the way

Play interrupts only for an adequate saved Play or a projected approval. When qualification
returns conversation or exclusion, or no adequate Play exists, Play exits quietly — no search
narration, no explore offers; the runtime arms its save hook on the way out. Saving, publication,
adapter repair, and team invites run only through the projected specialist handoffs. Never
decompose `rote play run` into registry pulls, adapter setup, or local-path execution, and never
treat its failure as authorization for a manual fallback. Preserve every primary payload exactly
as received; compact summaries are incomplete results. Never place raw credentials in Play
context, packets, logs, or responses.

## Fail closed

Stop with the projected blocker on an undeclared event, invalid payload, continuation or bundle
mismatch, missing authority, unavailable specialist, declined approval, invalid receipt, or
unverifiable outcome. Never infer success from specialist prose. At a terminal state present only
the projected receipt, completed, exited, or blocked outcome — a saved Play is complete only when
its birth certificate has been presented.
