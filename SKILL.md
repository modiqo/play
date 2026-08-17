---
name: play
description: >
  Sidekick for reusable procedures. Use when the user explicitly invokes Play, a Play hook names a
  relevant saved procedure or recommends a search, or a verified capture is ready to settle. Play
  also handles its cheat sheet, onboarding, canonical Play URIs, digest, management, sharing, and
  birth certificates.
---

# Play

Play's typed runtime owns all control flow. Your job at each yield is small and local. Never read
`machine.yaml`, `actions.yaml`, `prompts.yaml`, schemas, or reference files during a run — the
returned projection is the entire instruction contract for the current moment.

## Activation gate

Enter Play only when the user explicitly invokes Play or the prompt hook injected a Play activation
line. An ordinary outcome with no hook activation continues normally; do not independently enroll it
in Play merely because it could become reusable. The hook may remain silent because a validated user
or project routing policy selected direct API/CLI execution; honor that silence and do not recreate
Play activation from provider or tool names in the request.

If the unchanged request begins with `direct:` or `without play:`, treat the remainder as a one-turn
hard bypass. Do not run `play-machine`, search, capture, update Play preferences, or create a settle
nudge. Continue with the requested work directly. This bypass affects only Play orchestration; it
does not bypass harness permissions, safety checks, or tool approvals. Do not convert it into a
persistent mode or infer it from vague dissatisfaction.

If the unchanged trimmed request is `play cheat-sheet`, `$play cheat-sheet`, or
`/play cheat-sheet` (also accept `cheat sheet` or `cheatsheet` spelling), do not enter the state
machine or run preflight. Run the bundled `scripts/bin/play-cheat-sheet`, present its Markdown
verbatim, and stop. This read-only help path must not search, capture, update preferences, or create
a settle nudge.

## Enter or resume

For an activated new task run `play-machine run-until-yield --stdin --json` with a harness-owned run
ID, stable task key, and the unchanged user request:

```json
{"run_id":"<run-id>","task_key":"<task-key>","request":{"original":"<request>"}}
```

The installer normally places `play-machine` on `PATH`. If it is unavailable but this loaded skill
contains executable `scripts/bin/play-machine`, first run bundled `scripts/bin/play-activate` to
repair the launcher and activation state, then enter the runtime through the bundled
`scripts/bin/play-machine` for this turn. Do not wait for shell command hashing or a harness restart.
If activation repair fails, run bundled
`scripts/bin/play-preflight --harness <codex|claude|kimi|cursor|hermes|opencode|deepseek|generic> --json`, present its exact
failed checks and multi-select install targets, report that the Play installation is incomplete,
and stop before normal Play control flow. Do not try `rtk` or `rtk proxy`: `play-machine` is a Python
entrypoint installed through a small executable launcher, not an RTK subcommand or compiled Python
artifact. An explicit `/play` or `$play` with no separate task is a complete
onboarding request: set `request.original` to `/play`. When the terminal presentation returns a
capture handle, do all subsequent work through its named Rote workspace. Only after that captured
trajectory verifies may you re-enter with `$play settle <capture-handle> <one-line summary>`.
Never settle normal/uncaptured work or reconstruct a trajectory after the fact.

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
`play-machine preflight --harness <codex|claude|kimi|cursor|hermes|opencode|deepseek|generic> --json` first and pass its complete
unchanged output as `preflight`. Missing Rote setup delegates to the `rote-setup` skill.
When the preflight is structurally healthy and its only failed check is `authenticated`, treat that
as the normal first-use entrance, not an error or blocker: keep the Play continuation opaque, invoke
`rote-setup`, and lead with sign in or create an account through Google or GitHub. After the setup
specialist verifies `rote whoami`, rerun the complete preflight and resume the same declared event
with the now-ready output. If the user pauses setup, preserve the original request and say how to
resume it; do not replace the requested outcome with a generic installation failure.

## Cross-harness bootstrap

For an explicit request to install or repair Play across harnesses, use the bundled
`scripts/bin/play-bootstrap` only after the typed runtime returns the task to normal execution.
Run `plan --json` first, present its multi-select top-K targets and effects, and obtain approval for
that exact `plan_id`. Then run `apply --plan-id <id>`; add `--approve-remote-installer` only after
the user separately approves the official Rote installer. If the receipt reports
`human_action_required`, invoke the installed `rote-setup` skill through the harness, then rerun a
fresh plan/apply convergence pass. Never collect credentials in bootstrap context or reports.

## Stay out of the way

Play interrupts only for an adequate saved Play or a projected approval. When qualification
returns conversation or exclusion, or no adequate Play exists, Play exits quietly — no search
narration, no explore offers. Before novel outcome work starts, the runtime classifies it as
`capture` or `normal`. Capture creates a Rote workspace and handle; normal creates neither.
**A standby exit is a baton-pass, never a result**: complete a captured request only through the
returned workspace, or complete a normal request without a future settle option. Saving, publication,
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
