---
name: play
description: >
  Sidekick for reusable procedures. Use only when the user explicitly invokes Play. Play runs and
  creates reusable procedures and manages its cheat sheet, onboarding, canonical Play URIs, digest,
  routing policy, management, sharing, and birth certificates.
---

# Play

Play's typed runtime owns all control flow. Your job at each yield is small and local. Never read
`machine.yaml`, `actions.yaml`, `prompts.yaml`, schemas, or reference files during a run — the
returned projection is the entire instruction contract for the current moment.

## Activation gate

Enter Play only when the user explicitly invokes Play. An ordinary outcome continues normally; do
not independently enroll it in Play merely because it could become reusable. The discovery hook may
surface a saved Play, but it never activates Play or Rote and never loads their state.

The harness-native prefix activates Play. Use `$play` in Codex and `/skill:play` in Kimi Code. Use
`/play` in Claude Code, Cursor, Hermes, OpenCode, or DeepSeek Harness.

Without that explicit prefix, Play stays silent and out of the agent's way.

A hook line beginning `Play suggestion:` is not Play activation. The hook has already searched
installed Plays and the refreshed authorized catalog cache. Present only the exact quiet or passive
one-line suggestion quoted by the hook. Do not pause, enter the state machine, search again, pull,
inspect, run, or invoke Rote. Continue the original request through the normal harness route. The
user may explicitly invoke the named Play or ask to search later.

### Scheduling begins only after the result

Treat scheduling as a post-result action. Before Play returns a verified successful receipt, never
mention scheduling, probe Tulving, ask a recurrence question, or offer a cadence. Present the
complete result before taking any scheduling action.

Identification, inspection, pull or replace approval, installation, credentials, parameters, and
execution approval do not cross this barrier. A domain result called a receipt, such as a ride-share
receipt, is not a verified Play receipt. Do not treat a request to pull and run as a scheduling
request.

An explicit scheduling request may use the scheduling path without a new run. It still requires an
exact versioned reference from a prior verified receipt.

If the unchanged request begins with `direct:` or `without play:`, treat the remainder as a one-turn
hard bypass. Do not run `play-machine`, search, capture, update Play preferences, or create a settle
nudge. Do not invoke any Rote skill, CLI, adapter, workspace, search, or routing layer. Continue with
the requested work through harness-native tools or the relevant vendor API/CLI. This whole-turn
bypass includes inference continuations, delegation, retries, and tool loops; it does not bypass
harness permissions, authentication, safety checks, or tool approvals. Do not convert it into a
persistent mode or infer it from vague dissatisfaction.

If the unchanged trimmed request is `play cheat-sheet`, `$play cheat-sheet`, `/play cheat-sheet`, or
`/skill:play cheat-sheet` (also accept `cheat sheet` or `cheatsheet` spelling), do not enter the state
machine or run preflight. Run the bundled `scripts/bin/play-cheat-sheet`, present its Markdown
verbatim, and stop. This read-only help path must not search, capture, update preferences, or create
a settle nudge.

If the unchanged request begins with `play guide`, `$play guide`, `/play guide`, or
`/skill:play guide`, do not enter the state machine or run preflight. Run the bundled
`scripts/bin/play-guide --harness <current-harness>`, followed by any guide topic or question words.
Use `codex`, `claude`, `kimi`, `cursor`, `hermes`, `opencode`, or `deepseek` as the harness value.
Present its Markdown verbatim and stop.

This read-only guide must not authenticate, search, pull, run, crystallize work, update preferences,
or create a continuation. It may explain scheduling as a later capability. It must never probe
Tulving, offer a cadence, or create a schedule.

If the unchanged request is `play journal`, `$play journal`, `/play journal`,
`/skill:play journal`, or asks to show the Play recall journal, do not enter the state machine or
run preflight. Run the bundled
`scripts/bin/play-journal show --day today` and present its Markdown verbatim. Accept `yesterday`
or an explicit `YYYY-MM-DD` after `journal` and pass that value to `--day`. This owner-private,
read-only view aggregates typed saved-Play match, selection, run, completion, and blocker events;
it never searches the registry or stores prompt text or credentials.

If the unchanged request is `play journey live`, `$play journey live`, `/play journey live`,
`/skill:play journey live`, or asks to open the active exploration's live Journey map, do not enter the state machine or run
preflight. Run the bundled `scripts/bin/play-journey view --active`. It resolves the current Rote
workspace owner-privately, overlays its matching active capture when available, continuously syncs
new workspace commands, and replaces older Journey HTTP
servers with one token-protected read-only singleton on `127.0.0.1:52050`, opens the
deterministic isometric map, prints its local URL, and returns immediately. It must never start a
capture, invoke Rote, expose the capture reference, or authorize an effect. If no active Journey is
ready, present the CLI's exact blocker and leave the exploration unchanged.

The viewer wakes a selected live workspace's projector every five seconds for two minutes. It then
returns to the ten-second calm cadence. The read-only refresh stops following the old workspace
when selection changes.

If the unchanged trimmed request is `play what's new`, `$play what's new`, `/play what's new`, or
`/skill:play what's new` (also accept `whats new`, `popular Plays`, or `trending Plays`), do not enter the state machine, run
preflight, or create a continuation. Run the bundled
`scripts/bin/play-digest --remember --days 7`, present its Markdown verbatim, and stop. The digest
uses the install-warmed catalog cache when fresh and performs its own bounded refresh otherwise. A
later request must explicitly invoke Play to inspect or run one of the displayed Plays.

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

For recurring Play inspection or management, use the installed `play recurring` facade. Do not
enter the state machine for these owner-private operations:

- “What is running?” maps to `play recurring list --json`. Add `--all` when retired schedules matter.

- “What changed?” maps to `play recurring recall --since <checkpoint> --changed`.

- “What failed?” maps to `play recurring recall --since <checkpoint> --failed`.

- “What was the last run?” maps to `play recurring last`. Add the schedule ID when the request
  names one schedule. This returns the newest completed envelope and ignores missed-run markers.

- “Check my inbox” runs both recall views, then `play recurring list --all --json` for retirements.
  Use the caller's owner-private last-checked time and advance it only after display. Compare schedule
  status with the prior view when one exists. Surface movement, failures, misses, and retirements;
  when nothing moved, say so once.

- “Why does this run?” maps to `play recurring why <id>`. New reason text changes stored intent.

- “Run it now” maps to `play recurring now <id>` and returns the new envelope unchanged.

- “Stop it” maps to `play recurring stop <id>`. Use `--all` only when the user names every schedule.

- “Quiet it” maps to `play recurring snooze <id> <duration>`. Prefer snooze for temporary pauses.

- Clock health maps to `status`; clock control maps to `clock on` or `clock off`.

- A ledger backup maps to `export <path>`. An update check maps to `update`.

`play recurring update` checks only; `--apply` requires explicit update approval. Use `recall` JSON
lines and `list --json` for reasoning. Keep other list output, `changed`, and `digest` as terminal
views; never parse them. Keep Tulving's `every` and `add` writes behind `play recurring schedule`;
never call its OS-owned `tick` or transport-owned `mcp` process directly.

If the request explicitly asks to schedule a known or completed Play, use the installed
`play recurring` facade. Do not enter the state machine again. Run `play recurring probe` first.
Continue only when its Tulving capability is `ready`.

If Tulving is unavailable, report that recurring Plays are off and do not invoke `tulving add`.
Schedule only an exact versioned reference from a verified receipt. Preserve approved parameters as
repeated `--parameter name=value` arguments. Require `--why`, default to `--for 30d`, and reject
bare or latest references.

Translate recurring intent into Tulving fields:

- A fixed lifetime uses `--for`, `--max-runs`, or `--expires-at`.

- “Until it resolves” uses `--until` with a result predicate.

- A threshold alert uses `--on` and an approved `--notify` command.

- A value watch uses `--on-change`; add its JSON pointer when the user names one field.

- A catalog watch adds `--key <pointer>` so additions, removals, and changes become deltas.

- Context uses repeatable `--tag`, plus `--session` and `--cwd` when the verified run supplies them.

Play validates one unchanged spec through `tulving add - --dry-run`. It checks
`play recurring list --all --json` before committing. An active schedule with the same Play and
parameters blocks creation. Offer `play recurring now <id>` when the user wants a first envelope.

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
artifact. An explicit `$play`, `/play`, or `/skill:play` with no separate task is a complete
onboarding request: preserve that exact form in `request.original`. When the terminal presentation returns a
capture handle, do all subsequent work through its named Rote workspace. Only after that captured
trajectory verifies may you re-enter with `$play settle <capture-handle> <one-line summary>`.
Never settle normal/uncaptured work or reconstruct a trajectory after the fact.

During an active exploration, treat `instruction.input.execution.workspace_path` as the only
execution directory. It is an absolute path. Enter it in the same shell invocation before every
Rote command (`cd -- "<workspace-path>" && rote ...`); never run `rote cd` as a separate command,
assume a previous shell call changed directory, substitute another workspace, or execute from the
repository. This invariant covers prerequisites, routing, retries, refinements, and resumed work.
If the harness requires filesystem permission for that path, retain the same access when resuming
`play-machine` so the runtime can verify the recorded trajectory. A `direct:` side-step remains
outside this workspace and never contributes evidence.

If runtime re-entry reports that it could not verify the captured Rote trajectory, keep the
continuation active. Do not repeat the outcome work, switch tools, or return
`exploration_route_exhausted`. Correct only the reported workspace, authentication, database, or
filesystem-permission problem, then resubmit the unchanged `exploration_outcome_ready` event. The
runtime runs its own `rote ls` and `rote trace --deps` checks; manually repeating those checks does
not bind evidence to Play.

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

When the discovery hook names a Play, preserve that complete canonical `owner/name` reference in
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

Tool, shell, and model-context output does not count as delivery. Copy the exact Markdown for each
presentation into a message the user can see. Do not replace the primary payload with a
recap or totals. Do not claim that the result was “shown above” unless its literal payload appears
in chat.

Finish delivery before you call another tool. This includes `play recurring probe` and structured
elicitation. If opening a picker could hide the assistant message, end with the complete result and
verified receipt. Omit the recurrence picker; the user can request scheduling later without a new
run.

- `model`: reason over only `instruction.input` and the projected policy; return one declared
  event by filling `event_template` according to its complete `payload_schema`; never guess field
  types, enum values, or nested object shapes from the field names alone. Keep `request.intent`
  a short outcome phrase (`pricing page assessment`), never a sentence carrying URLs, paths,
  handles, or dates; those are parameters. Search runs the intent and the user's original words
  together and strips argument values itself, but a lean intent keeps every harness on the same
  footing. For
  `route_inspected_play`, resolve every parameter the
  user already supplied against the inspected frontmatter in one pass, normalize it to the declared
  type/description/example/valid values/input choices, and return the complete canonical
  `request.parameters`. Collect every value that is genuinely missing, ambiguous, or invalid in one
  structured prompt. After the user answers, normalize all supplied values together and ask again
  only for fields that remain unresolved. Never forward conversational shorthand as an execution
  parameter when frontmatter declares a stricter format.
- `human`: present the exact projected prompt through structured elicitation; resume with the
  selected declared event. The projection carries `instruction.presentation` with verbatim
  Markdown, a label-to-event map, and fidelity rules. Show every projected choice with its exact
  label and description, in the projected order. Never add, remove, rename, merge, or re-describe
  a choice; a choice that is not projected does not exist. The user's original words never
  remove a choice and never answer the prompt, so do not pre-decide, pre-select, or skip it on
  their behalf. Resume only with the event bound to the choice the user selected. The runtime
  rejects any other event and names the declared ones; when that happens, show the projected
  prompt again unchanged.
- `specialist`: invoke only `instruction.specialist` with `instruction.input` through the
  harness's skill mechanism; resume with the one accepted typed receipt event. Interactive
  specialists own their own user questions — ask those directly and continue inside the
  specialist flow; return to the runtime only with a declared receipt event.
- `terminal`: present the terminal outcome and stop.

Present the complete result and its verified receipt unchanged. End that assistant turn after the
result is visible. Never open a recurrence picker or call another tool in the same turn. A harness
prompt can hide mid-turn text.

For an eligible run, place one passive line after the receipt.

`↻ Want this to repeat? Ask <Play prefix> schedule this.`

This includes a first remote pull or replacement and a run of an already-local exact version.

Do not use the choice for the onboarding starter, a failed or blocked run, or an interactive Play.
Do not use it for an inspection with writes or unverified effects.

Result delivery is an atomic checkpoint. Place the literal primary payload and receipt in chat and
end the assistant turn. A summary is not delivery. Do not run `play recurring probe`, open a picker,
or depend on mid-turn text after a completed run.

A later scheduling request starts with `play recurring probe`. Then offer **Hourly**, **Daily**,
**Choose cadence**, or **Not now** for that exact completed Play.

Treat the choice as per-run consent. On acceptance, invoke `play recurring schedule`. Pass the
exact version, parameters, reason, cadence, and stop condition. Add supported use-case fields, then
present Tulving's schedule receipt.

If the capability is not ready, end with the Play receipt. Do not mention or invoke scheduling.
A later scheduling request uses the explicit path above. Do not require another Play run.

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

Play keeps registry sign-in recovery inside the pending request. When `rote play run` reports that
Rote is signed out, show the Google, GitHub, and **Not now** choices.

The bundled runtime runs only the selected `rote login --provider ...` command and one `rote whoami`
check. A verified login returns Play to the exact inspected reference, parameters, disclosure, and
run approval.

Do not invoke the general `rote-setup` wizard. Do not discuss adapters, ask the user to retry the
Play, or start a new request. A failed login shows the same provider choice without running the
Play.

Never run full Play preflight during a normal request. Install-time convergence owns cross-harness
readiness; the normal runtime owns its exact dependency and authentication states and projects a
targeted setup or login handoff only when one is actually required. `play-machine preflight` is a
diagnostic for explicit install/repair work, not an execution gate. A continuation exists only at a
real model, approval, specialist, or user-choice boundary; keep its short ID opaque and never narrate
or inspect continuation machinery.

## Audit: advisory, never gating

Every Play inspection now ends with a report card: what the Play does in order,
what it touches, what this machine has, and whether it can run here. The card is
advisory. It never withholds the run prompt, and an audit that cannot run is
simply absent. Present the card as part of the disclosure; do not summarize it
away and do not turn it into a list of problems for a consumer.

On the creation side, after the verified run and before `rote play release`,
the authoring specialist runs `scripts/bin/play-audit fixtures <path>` to pack
the run's observations as fixtures plus partial, truncated, and blocked cases per
step, then `scripts/bin/play-audit rehearse <path>` to show the author the
stock-macOS card and any negative case the presentation misreports. Offer
`scripts/bin/play-audit handoff <path> --rule ...` for findings the author
chooses to fix; release proceeds whatever they choose.

For a user asking about a Play they did not write, `play audit <ref> --author`
is the work order and `play audit <ref> --report` the note for its author.
Facts are provable from the package; judgments are advisory and say so.

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
needed. A successful install prints a tutorial for automatic discovery, non-blocking suggestions,
silent no-match behavior, explicit Explore commands, and approval before pull or execution.
Never collect credentials in bootstrap context, backups, or reports.

Treat Play, Rote, and Tulving as independent release cycles under one setup receipt. The plan checks
Rote's own update channel and refreshes its installed skills after a Rote update. It checks
Tulving's own update channel and requires separate default-no approval before installation, update,
or clock initialization. Play replacement remains its own restorable transaction. Never claim that
Play rollback downgrades Rote or Tulving; report every component's before and after version.
When the user asks to update Play itself, use `play update`. It downloads the latest official source
over HTTPS. It then enters the first installer's planned, backed-up, verified convergence flow. Do
not ask an already-installed user to paste the curl bootstrap again.

Use `rote whoami --check` at every Play-owned identity boundary. It refreshes usable authentication and
returns exit `77` only when login is required. After a verified Google or GitHub login, remember
only that provider name in Play's owner-private state.

On a later exit `77`, run `rote login --provider <remembered-provider>` automatically. Require a
successful `rote whoami --check` before continuing. If no provider is known, ask once. Never start
login for a network, configuration, or persistence error. Never store tokens or email in the
preference.

## Stay out of the way

Automatic hook discovery searches installed Plays and the refreshed authorized catalog cache.
Strong matches produce one quiet suggestion and continue the normal harness route. Weak matches and
no matches produce no Play output. Discovery never reads Play preferences, journals, exploration
state, or Rote workspaces.

When an explicitly activated outcome search finds no adequate Play, the runtime exits quietly and
the harness continues the unchanged request normally. An explicit Play search may show an empty
result, then stops without offering creation. Only `$play explore <outcome>`,
`/play explore <outcome>`, or `/skill:play explore <outcome>` authorizes the creator path. That path searches local and authorized
registry Plays first. If none matches, the next deterministic transition creates the capture and
Rote workspace before any work begins, then yields directly to the `rote` specialist without a
second exploration prompt. That specialist must invoke
`rote-task-routing`; API adaptation belongs to `rote-adapter-create`, existing CLI discovery and
validation belong to `rote-shell` using `rote deps` and `rote proc`, and adapter execution belongs
to `rote-workspace`. Present the discovered routes, always allow another tool, wait for the user's
selection, verify that selection, and announce the first outcome-bearing step before execution.
Continue the original outcome through that returned workspace. Never invent a second search picker
or ask for the outcome again. Before novel outcome work starts, the runtime classifies it as
`capture` or `normal`; explicit Explore selects `capture` after an empty search. Capture creates a
Rote workspace and handle; normal creates neither. A terminal `exited` state with no Play result is
a typed handoff back to the harness: continue the unchanged original request normally and never
offer a future settle action for that work.
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
Only an explicitly active captured exploration may display workspace analytics. Ambient hooks never
show progress or Rote workspace statistics.
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
Do not search for another Play, offer a new exploration, or recommend `direct:`; direct mode
bypasses both Play and Rote and therefore cannot complete the governed publication lifecycle.

## Fail closed

Stop with the projected blocker on an undeclared event, invalid payload, continuation or bundle
mismatch, missing authority, unavailable specialist, declined approval, invalid receipt, or
unverifiable outcome. Never infer success from specialist prose. At a terminal state present only
the projected receipt, completed, exited, or blocked outcome as the primary result. The post-receipt
recurring choice above is the sole permitted follow-up to an ordinary verified receipt; a saved Play
is complete only when its birth certificate has been presented.
