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
in Play merely because it could become reusable. A hook line beginning `Play direct bypass:` is a
negative route, not Play activation. Honor it for the complete user turn, including every inference,
delegation, retry, and tool loop: do not invoke Play or Rote skills, CLIs, runtimes, searches,
adapters, workspaces, capture, or follow-up routing. Use harness-native tools or only the matched
vendor API/CLI path named by the hook.

If the unchanged request begins with `direct:` or `without play:`, treat the remainder as a one-turn
hard bypass. Do not run `play-machine`, search, capture, update Play preferences, or create a settle
nudge. Do not invoke any Rote skill, CLI, adapter, workspace, search, or routing layer. Continue with
the requested work through harness-native tools or the relevant vendor API/CLI. This whole-turn
bypass includes inference continuations, delegation, retries, and tool loops; it does not bypass
harness permissions, authentication, safety checks, or tool approvals. Do not convert it into a
persistent mode or infer it from vague dissatisfaction.

If the unchanged trimmed request is `play cheat-sheet`, `$play cheat-sheet`, or
`/play cheat-sheet` (also accept `cheat sheet` or `cheatsheet` spelling), do not enter the state
machine or run preflight. Run the bundled `scripts/bin/play-cheat-sheet`, present its Markdown
verbatim, and stop. This read-only help path must not search, capture, update preferences, or create
a settle nudge.

If the unchanged request is `play journal`, `$play journal`, `/play journal`, or asks to show the
Play recall journal, do not enter the state machine or run preflight. Run the bundled
`scripts/bin/play-journal show --day today` and present its Markdown verbatim. Accept `yesterday`
or an explicit `YYYY-MM-DD` after `journal` and pass that value to `--day`. This owner-private,
read-only view aggregates typed saved-Play match, selection, run, completion, and blocker events;
it never searches the registry or stores prompt text or credentials.

If the unchanged request is `play journey live`, `$play journey live`, `/play journey live`, or
asks to open the active exploration's live Journey map, do not enter the state machine or run
preflight. Run the bundled `scripts/bin/play-journey view --active`. It resolves the current Rote
workspace owner-privately, overlays its matching active capture when available, continuously syncs
new workspace commands, and replaces older Journey HTTP
servers with one token-protected read-only singleton on `127.0.0.1:52050`, opens the
deterministic isometric map, prints its local URL, and returns immediately. It must never start a
capture, invoke Rote, expose the capture reference, or authorize an effect. If no active Journey is
ready, present the CLI's exact blocker and leave the exploration unchanged.

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
invoke Rote, capture work, update preferences, handle credentials, or claim that routing changes
harness permissions or safety checks.

If the request explicitly asks to schedule a known Play or keep the completed Play running, use the
bundled `scripts/bin/play-recurring` CLI. Do not enter the state machine again. Run
`play-recurring probe` first. Continue only when its Tulving capability is `ready`.

If Tulving is unavailable, report that recurring Plays are off and do not invoke `tulving add`.
Schedule only an exact versioned reference from a verified receipt. Preserve approved parameters as
repeated `--parameter name=value` arguments. Require `--why`, default to `--for 30d`, and reject
bare or latest references.

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

When the activation hook names a Play, preserve that complete canonical `owner/name` reference in
every `match.reference` event. Never shorten it to the bare Play name, reconstruct an owner, or use
digest display text as identity. The runtime can resolve a unique bare name from its complete cached
catalog as a compatibility safeguard, but the hook-supplied canonical reference remains authoritative.

## Handle the yield

Present returned `presentations` in order, then act on `projection.state.boundary`:

Returned presentations are a blocking delivery queue, not optional context. Deliver every primary
result completely before showing or acting on the projected prompt. On first-use Hello, never move
past `confirm_onboarding_result` until the user confirms the result is visible. If the harness marks
the tool response as truncated, or the result is absent from chat, offer or select only **Show result
again**; the replay turn contains the unchanged result without activation guidance or next actions.
Never infer confirmation, choose **Yes, continue** for the user, or summarize a missing result.

- `model`: reason over only `instruction.input` and the projected policy; return one declared
  event by filling `event_template` according to its complete `payload_schema`; never guess field
  types, enum values, or nested object shapes from the field names alone. For
  `route_inspected_play`, resolve every parameter the
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

After presenting an ordinary successful Play receipt unchanged, there is one optional follow-up.
Do not use it for the onboarding starter, a failed or blocked run, an interactive Play, or an
inspection with writes or unverified effects. For an eligible receipt, run `play-scheduler-probe`
after the receipt is visible. Continue only when its `tulving` capability is `ready`.

Ask whether to repeat that exact Play: **Hourly**, **Daily**, **Choose cadence**, or **Not now**.
This is a per-run choice, never standing consent. On acceptance, invoke `play-recurring schedule`
with the exact versioned reference and approved parameters. Add a concise reason, `--for 30d`, and
then present Tulving's schedule receipt.

If the capability is not ready, end with the Play receipt. Do not mention or invoke scheduling.

Authentication declared by a saved Play stays inside its approved `rote play run`. When inspection
shows `adapter.auth.ensure`, complete secure browser-capable provider sign-in inside that step and
continue the same run; never run `rote oauth` separately or synthesize an authentication receipt for
it. A missing static credential is the exception because the step can detect but cannot mint a
vendor secret: follow the projected `rote-adapter-config` boundary, resolve only the adapter
catalog's first-party HTTPS token page, and tell the user to create the token there and run
`rote token set <ENV> --stdin` in their own terminal. Never request or receive the token in chat.
Only after the user confirms the out-of-band command and the named token is verified may Play retry
the exact approved run. An older Play without `adapter.auth.ensure` may also enter the explicit
compatibility path after its run reports authentication is required.

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
unrelated harness settings. Installation requires an authenticated Rote identity. A logged-out
non-interactive install exits before changing Play-owned state unless it names Google or GitHub as
the login provider. Re-run interactively when a browser sign-in or harness permission change is
needed.
Never collect credentials in bootstrap context, backups, or reports.

## Stay out of the way

Play interrupts only for an adequate saved Play or a projected approval. When qualification
returns conversation or exclusion, Play exits quietly. When the completed local and authorized
registry search has no matching Play, present the runtime's single **Explore and create** choice.
If the user accepts, the next deterministic transition creates the capture and Rote workspace
before any work begins, then yields directly to the `rote` specialist. That specialist must invoke
`rote-task-routing`; API adaptation belongs to `rote-adapter-create`, existing CLI discovery and
validation belong to `rote-shell` using `rote deps` and `rote proc`, and adapter execution belongs
to `rote-workspace`. Present the discovered routes, always allow another tool, wait for the user's
selection, verify that selection, and announce the first outcome-bearing step before execution.
Continue the original outcome through that returned workspace. If the user
declines, stop without creating a workspace. Never invent a second search picker or ask for the
outcome again. Before novel outcome work starts, the runtime classifies it as `capture` or `normal`;
the explicit empty-search approval always selects `capture`. Capture creates a Rote workspace and
handle; normal creates neither.
Adapter installation, authentication, token verification, capability probes, and connection smoke
tests are prerequisites rather than completed exploration outcomes. Continue from them to the
original requested outcome inside the same capture. Classify `connect to <provider>` as setup-led:
after connection, ask what useful outcome the user wants to explore. Classify `connect to
<provider> and <outcome>` as goal-bound: after connection, continue the already-declared outcome
without asking again. If a prerequisite must cross a specialist boundary, return
`exploration_prerequisite_ready`; only useful outcome-bearing work may return
`exploration_outcome_ready` or enter save judgment. A same-task refinement received at save
judgment resumes the same capture and workspace; never close it as one-off and restart search.
Deliver every deterministic exploration transition presentation: start, prerequisite-ready,
recovery, verified completion, and one-off completion. On a recoverable route failure, show the
projected recovery choice instead of silently changing tools. A `direct:` request during exploration
does not consume the Play continuation or import direct work into the captured evidence. Complete
that one direct turn, state that exploration remains paused, and resume the same workspace only
when the user says `continue exploration`, revalidating any external state that changed.
Only an active captured exploration may display workspace analytics. Its Stop hook stays silent
until both the configured step interval and time throttle are due, then shows one compact pulse;
ordinary requests and recalled Play runs never show Rote workspace statistics.
**A standby exit is a baton-pass, never a result**: complete a captured request only through the
returned workspace, or complete a normal request without a future settle option. Saving, publication,
adapter authentication, and team invites run only through the projected specialist handoffs. Never
decompose `rote play run` into registry pulls, adapter setup, or local-path execution, and never
treat its failure as authorization for a manual fallback. Preserve every primary payload exactly
as received; compact summaries are incomplete results. Never place raw credentials in Play
context, packets, logs, or responses.

Publishing an already saved, locally released Play is a lifecycle continuation, not a new workflow
request. Route it to the read-only local-release inspection state, recover and verify its originating
workspace trajectory, capture its birth, then enter the requested Rote registry publication path.
Do not search for another Play, offer **Explore and create**, or recommend `direct:`; direct mode
bypasses both Play and Rote and therefore cannot complete the governed publication lifecycle.

## Fail closed

Stop with the projected blocker on an undeclared event, invalid payload, continuation or bundle
mismatch, missing authority, unavailable specialist, declined approval, invalid receipt, or
unverifiable outcome. Never infer success from specialist prose. At a terminal state present only
the projected receipt, completed, exited, or blocked outcome as the primary result. The post-receipt
recurring choice above is the sole permitted follow-up to an ordinary verified receipt; a saved Play
is complete only when its birth certificate has been presented.
