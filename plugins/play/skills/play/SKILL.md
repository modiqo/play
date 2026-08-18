---
name: play
description: >
  Sidekick for reusable procedures. Use when the user explicitly invokes Play, a Play hook names a
  relevant saved procedure or recommends a search, or a verified capture is ready to settle. Play
  also manages direct-routing policy from natural-language requests and handles its cheat sheet,
  onboarding, canonical Play URIs, digest, management, sharing, and birth certificates.
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

If the unchanged trimmed request is `play what's new`, `$play what's new`, or `/play what's new`
(also accept `whats new`, `popular Plays`, or `trending Plays`), do not enter the state machine, run
preflight, or create a continuation. Run the bundled
`scripts/bin/play-digest --remember --days 7`, present its Markdown verbatim, and stop. The digest
uses the install-warmed catalog cache when fresh and performs its own bounded refresh otherwise. A
later request to inspect or run one of the displayed Plays is a new, naturally activated request.

For a request whose primary intent is to initialize, inspect, add, update, or remove Play's direct
routing policy, do not enter the state machine or run preflight. Translate the unchanged request to
the bundled `scripts/bin/play-routing` CLI:

- Default an unqualified request to `--project <workspace-root>`. Treat “this repo”, “this project”,
  “here”, or “local” the same way. Use `--user` only when the user explicitly says user, global,
  everywhere, all projects, or every project.
- Treat an unqualified setup request such as “Initialize Play routing” as
  `--project <workspace-root> init`. This is the default routing-management action and must not
  overwrite an existing policy.
- Map initialize/setup to `init`; show/list/inspect to `list`; add/route/update to `add`; and an
  explicit remove/delete/stop/disable request to `remove`.
- For `add`, derive a stable `<provider>-direct` ID from the named provider when no ID is given. Pass
  only provider and tool names actually stated by the user; let the CLI default executors to both
  API and CLI unless the request narrows them. Running `add` with an existing ID is an update.
- For `remove`, require an explicit removal verb. Use a stated route ID, or derive
  `<provider>-direct`; if neither is unambiguous, run `list` and ask which route to remove.
- After `init`, present the CLI status and policy path. After `add` or `remove`, run `list` for the
  same scope and present the resulting policy. A plain list request is read-only.

Never infer routing management from a provider task alone. “Deploy with Cloudflare” is direct work
when policy matches; “route Cloudflare directly in this repo” manages policy. Do not search Plays,
capture work, update preferences, handle credentials, or claim that routing changes harness
permissions or safety checks.

## Enter or resume

For an activated new task run `play-machine run-until-yield --stdin --json` with a harness-owned run
ID, stable task key, and the unchanged user request. Execute it as one non-interactive shell command
whose heredoc closes stdin; never start it as an interactive or background terminal process:

```sh
play-machine run-until-yield --stdin --json <<'PLAY_INPUT'
{"run_id":"<run-id>","task_key":"<task-key>","request":{"original":"<request>"}}
PLAY_INPUT
```

The installer normally places `play-machine` on `PATH`. If it is unavailable but this loaded skill
contains executable `scripts/bin/play-machine`, first run bundled `scripts/bin/play-activate` to
restore the launcher and activation state, then enter the runtime through the bundled
`scripts/bin/play-machine` for this turn. Do not wait for shell command hashing or a harness restart.
If activation restoration fails, run bundled
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
owner-privately under `~/.rote-play/continuations` and expires it after 24 hours. Resume with the
same one-shot heredoc form:

```sh
play-machine run-until-yield --stdin --json <<'PLAY_INPUT'
{"continuation_id":"<24-character-id>","event":{"id":"<event>","payload":{},"guards":{}}}
PLAY_INPUT
```

## Handle the yield

Present returned `presentations` in order, then act on `projection.state.boundary`:

Returned presentations are a blocking delivery queue, not optional context. Deliver every primary
result completely before showing or acting on the projected prompt. On first-use Hello, never move
past `confirm_onboarding_result` until the user confirms the result is visible. If the harness marks
the tool response as truncated, or the result is absent from chat, offer or select only **Show result
again**; the replay turn contains the unchanged result without activation guidance or next actions.
Never infer confirmation, choose **Yes, continue** for the user, or summarize a missing result.

- `model`: reason over only `instruction.input` and the projected policy; return one declared
  event with every required payload field. For `route_inspected_play`, resolve every parameter the
  user already supplied against the inspected frontmatter in one pass, normalize it to the declared
  type/description/example/valid values/input choices, and return the complete canonical
  `request.parameters`. Ask for only the first value that is genuinely missing, ambiguous, or
  invalid; never forward conversational shorthand as an execution parameter when frontmatter
  declares a stricter format.
- `human`: present the exact projected prompt through structured elicitation; resume with the
  selected declared event.
- `specialist`: invoke only `instruction.specialist` with `instruction.input` through the
  harness's skill mechanism; resume with the one accepted typed receipt event. Interactive
  specialists own their own user questions — ask those directly and continue inside the
  specialist flow; return to the runtime only with a declared receipt event.
- `terminal`: present the terminal outcome and stop.

Authentication declared by a saved Play stays inside its approved `rote play run`. When inspection
shows `adapter.auth.ensure`, complete secure provider sign-in inside that step and continue the same
run; never invoke `rote-adapter-config`, run `rote oauth` separately, or synthesize an authentication
receipt for it. Only an older Play without `adapter.auth.ensure` may enter the explicit
`rote-adapter-config` compatibility path after its run reports authentication is required.

Never run full Play preflight during a normal request. Install-time convergence owns cross-harness
readiness; the normal runtime owns its exact dependency and authentication states and projects a
targeted setup or login handoff only when one is actually required. `play-machine preflight` is a
diagnostic for explicit install/repair work, not an execution gate. A continuation exists only at a
real model, approval, specialist, or user-choice boundary; keep its short ID opaque and never narrate
or inspect continuation machinery.

## Cross-harness bootstrap

For an explicit request to install or restore Play across harnesses, use the bundled
`scripts/bin/play-bootstrap` only after the typed runtime returns the task to normal execution.
Run `plan --json` first, present its multi-select top-K targets and effects, and obtain approval for
that exact `plan_id`. Then run `apply --plan-id <id>`; add `--approve-remote-installer` only after
the user separately approves the official Rote installer. Apply first creates an owner-private,
restorable backup manifest under the Play bootstrap state directory, then fully replaces Play-owned
plugin, skill, hook, launcher, portable-copy, and activation-profile state while preserving
unrelated harness settings. A logged-out receipt is `onboarding_required`, not an install failure:
open a selected harness and invoke Play so its typed Google/GitHub login states can continue there.
Never collect credentials in bootstrap context, backups, or reports.

## Stay out of the way

Play interrupts only for an adequate saved Play or a projected approval. When qualification
returns conversation or exclusion, or no adequate Play exists, Play exits quietly — no search
narration, no explore offers. Before novel outcome work starts, the runtime classifies it as
`capture` or `normal`. Capture creates a Rote workspace and handle; normal creates neither.
**A standby exit is a baton-pass, never a result**: complete a captured request only through the
returned workspace, or complete a normal request without a future settle option. Saving, publication,
adapter authentication, and team invites run only through the projected specialist handoffs. Never
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
