---
name: play
description: >
  Use before tools or rote specialist skills when a user asks for an outcome that may be fulfilled
  by a reusable procedure. Search local and authorized Play indexes, run an adequate Play, or ask
  whether to explore with rote and preserve a new Play. Also use for Play onboarding, awareness,
  management, creation, publication, birth certificates, sharing, and canonical Play URIs.
---

# Play

> Think in terms of Plays before thinking in terms of tools.

Play's typed runtime owns the controller. The harness handles only declared model, human, and exact
specialist boundaries. Do not reconstruct or reread the state machine or implementation during a
run.

## Enter or resume the runtime

For a new task, call:

```text
play-machine run-until-yield --stdin --json
```

The installer places `play-machine` on `PATH`. Invoke it directly. Do not locate the skill, list its
directories, inspect its virtual environment, or prepend `uv run`. If the launcher is unavailable,
report that Play installation is incomplete and stop.

with a nonempty harness-owned run ID, stable task key, and the unchanged user request:

```json
{"run_id":"<run-id>","task_key":"<task-key>","request":{"original":"<request>"}}
```

An explicit `/play` or `$play` is a complete onboarding request. If the harness reports only that
the Play skill was activated and supplies no separate task, set `request.original` to `/play`.
Never substitute activation boilerplate or send this case to qualification.

The command creates the complete logical `play.context/v1`, executes eligible deterministic
actions, validates every event, applies context fields, checkpoints the transition, and stops only
at a boundary requiring model, user, or specialist work. It returns a short `continuation_id`; keep
that opaque value in harness/thread state. To resume, call the same command with the continuation
and the one declared event:

```json
{"continuation_id":"<24-character-id>","event":{"id":"<event>","payload":{},"guards":{}}}
```

Never inspect, edit, summarize, manufacture, print, or persist the continuation ID yourself. The
runtime stores its context owner-privately under `~/.rote/play/continuations`, expires it after 24
hours, and removes it at a terminal state. The harness must not copy controller context or a large
transport token between calls. If it cannot retain the short ID, emit `action_blocked` and stop.

The returned projection is the entire current instruction contract. It contains the current state,
boundary, bound input, exact action or prompt, and accepted event templates. Fill only null values
owned by the current boundary; preserve all prebound values. Do not read
`machine.yaml`, `actions.yaml`, `prompts.yaml`, or `context.schema.json` during a normal run. The
runtime already loaded, validated, and bundle-hash-bound them.

## Handle each yield

Follow only the returned `projection.state.boundary`:

- `model`: reason over only `instruction.input`, policy, and accepted events. Return one
  declared event with every required payload field. Evaluators are limited to request qualification,
  adequacy, creator reuse, route selection, and outcome verification.
- `human`: present the exact projected prompt through the harness's structured elicitation control.
  Resume with the selected declared event and its projected event template.
- `specialist`: invoke only `instruction.specialist` with `instruction.input` and its projected
  policy through the harness's skill mechanism. Resume only with one accepted typed receipt event.
  Do not read Play references or implementation to recreate the specialist's process.
- `terminal`: present only the terminal outcome described below and stop.

`runtime` is internal and must be consumed by `run-until-yield`; receiving it as a final boundary is
a controller defect. Do not execute its command manually or read source to repair it.

Pass returned `presentations` to the user in order before handling the final boundary. They are
complete milestone presentations, not debug output. Do not print the continuation ID, raw context,
transition record, command chatter, or evidence addresses.

If `instruction.preflight_required_for_events` contains the evaluator event you selected, run
`play-machine preflight --harness <codex|claude|generic> --json` after qualification and before
resuming. Include the complete unchanged `play.preflight/v1` JSON output as the `preflight` value;
do not reduce it to `{ "ready": true }`. Conversation and excluded repository work exit without
paying this probe. If setup is required, invoke the callable
`rote-setup` skill; Play never installs or authenticates Rote itself.

## Keep execution quiet and visible at milestones

Default to milestone-only updates: mode selection, search/run beginning, approval, exploration,
save/publication, blockers, and terminal results. Do not narrate fast deterministic transitions.
For non-interactive Rote execution, set `ROTE_FLOW_PROGRESS=0` and `ROTE_NO_HINTS=1` when safe, but
never suppress primary output, errors, approvals, effects, references, or receipts.

Present returned `presentations` and the projected human prompt directly. They are already compiled
for the current state. Do not locate or invoke a second presentation script during a normal run.

The runtime's universal Play runner executes the approved canonical URI or exact reference once.
Do not invoke `rote-flow-run`, rediscover the Play, resolve a local path, or perform a second capture
run. After execution, preserve the complete primary payload exactly as received and pass it directly to verification with its
declared source, format, manifest, truncation flag, and full-output reference. The harness owns
presentation; Play must not wrap, summarize, convert, or decorate the result. Compact summaries are
incomplete results.

## Trust the compiled trajectory

Do not load branch references during a normal run. The runtime projection carries the complete
state-local policy, prompt, bound event template, and exact specialist identity. Reference files are
for authoring and maintenance only, never an execution prerequisite.

## Preserve the Use contract

An adequate local Play follows:

```text
inspect → disclose → bind run handoff → universal Play runner → detailed output → verify → receipt
```

An adequate remote Play inserts `approve → pull/install` between disclosure and execution. Use
`scripts/bin/play-inspect <reference> --json` for read-only inspection. If inspection proves the
exact Play is already local, continue directly to the universal Play runner. If it reports install,
replacement, repair, or unknown local state, present the structured approval prompt and run only
after the approval binds the exact reference, parameters, and disclosure SHA.

Before execution, prepare `play.run-handoff/v1` with
`scripts/bin/play-handoff prepare-play-run --stdin --json`. This compact packet is the immutable
retry contract. If `rote play run` returns a recoverable adapter-authentication failure, ask for
repair approval, hand the packet and its SHA to `rote-adapter-config`, validate its receipt, inspect
again, and retry the exact Play. Play must not recreate the adapter configuration process.

`rote play run` owns installation, convergence, dependencies, credentials, and execution behind the
universal runner. Never decompose it into registry pull, adapter setup, local-path execution, or
lower-level commands. A failed `rote play` command is not a capability gap and never authorizes a legacy or manual fallback.

Present the resolved version, visibility, description, parameters, local status, dependencies,
credentials by name, operations, declared writes, blockers, and uncertainty. Generic adapter
operations do not prove read-only behavior. Never pipe input to automate a selector.

## Preserve Awareness and onboarding

Search local, every private authorized organization, and the authorized public hub only through
`scripts/bin/play-search`; require a complete scope-partitioned response, normalized canonical
references, and deduplicated versions. Outcome discovery ranks adequate matches local first,
private remote second, and public remote third. Local matches proceed after read-only inspection;
when only remote matches exist, present the ordered private/public choices instead of silently
selecting one. The selected remote match then requires explicit pull consent.

Digest requests use `scripts/bin/play-digest --remember`; its local cache stores only scope, SHA,
and UTC checkpoint. When unchanged, say only “Nothing new since your last Play check.” Otherwise
present the grouped Play inbox and truthfully labeled public-card lifetime metrics, never a false
time-window trend.

An empty `$play` or `/play`, activation with no separate task, and a canonical
`https://play.modiqo.ai/<owner>/<name>` URI use the typed onboarding trajectory. Missing Rote
delegates to `rote-setup`. A URI without Rote may fetch only the
exact HTTPS host without redirects, cookies, credentials, or custom headers, and may present only a
bounded matching `rote.play.v1` card. Never execute its install or bootstrap links.

First-use identity memory stores only a hashed identity, orientation version, and timestamp. The
Explore welcome treats the human as domain expert and the agent as apprentice. If identity cannot
be verified, use `friend`; do not invent a name or block approved exploration.

## Preserve Explore and handoff boundaries

For absent or inadequate matches, ask whether to Explore with Rote or continue normally. Do not
start a modality without Explore consent. Explicit create-a-Play intent grants Explore consent but
still preserves authentication, effects, widening, and publication gates.

Respect user modality constraints. CALL uses `rote-using-adapters`, SHELL uses `rote-shell`, DRIVE
uses `rote-browse`, and combined routes use `rote-workspace`. The selected owner must be callable in
the harness. An installed file, MCP server, app, or browser is not proof. Never call provider, shell,
browser, MCP, or app tools directly during `explore_execute`; invoke only the typed specialist.

CALL discovery delegates to `rote-adapter-create`, which searches installed adapters and then the
Rote catalog before documentation discovery. Show all catalog choices and never silently collapse
REST and MCP entries. A choice or proven catalog miss returns to `rote-adapter-create` for the whole
dry-run/create/initial-auth/readiness process; only an `installed_ready` receipt can reach
`rote-using-adapters`. Authentication repair must
arrive as `auth_repair_required`, receive explicit approval, use a separate
`rote-adapter-config` packet, and produce a validated repair receipt before a fresh execution packet.
Never place raw
credentials in Play context, tokens, packets, logs, or responses.

A Rote `confirmation_required` receipt must display the exact tool, impact, token, workspace, and
evidence. Approval binds those fields and resumes the same workspace for only that guarded call.
Decline or mismatch blocks. Probe hints never synthesize approvals or blockers.

## Preserve save and publication boundaries

Save is offered only after a verified candidate and the read-only public-owner probe. Choices are
Private, Public, or Skip. Private and Public authorize their declared release/publication sequence;
Skip remains unpublished exploration.

Publication is never a terminal milestone. Release and publication are separate specialist
invocations. `author_release` may return only an unpublished candidate. Capture the owner-private
birth object before publication; the publication-only receipt must echo the same birth SHA. If a
specialist publishes during release, emit `publication_boundary_violated` and block.

After publication, bind the birth, index the exact version, and inspect the canonical reference.
For Public, verify each adapter's source, version, fingerprint, auth family, and credential variable
names without reading credential values, then run the exact registry URI once from an isolated
temporary directory. Fingerprint equality alone is insufficient. Only matching readback and public
smoke verification may enter certificate presentation and `completed`.

The birth certificate must come from `scripts/bin/play-certificate --stdin --json`, use the exact
registry URI and same redacted trace, and provide paste-ready X and LinkedIn copy without posting it.

## Stop safely

Fail closed on an undeclared event, invalid payload, bundle/token mismatch, missing authority,
unavailable specialist, forbidden modality, declined exact effect, exhausted budget, incomplete
search/output, invalid receipt, or unverifiable outcome. Do not infer success from specialist prose.

At terminal state present only:

- `receipt`: the verified unchanged Use result and receipt;
- `completed`: the verified Explore, Awareness, management, onboarding, or birth result, including
  saved reference/certificate only when its full gates passed;
- `exited`: confirmation that Play stepped aside for this task;
- `blocked`: the precise missing authority, capability, valid output, or state evidence.

Never print “published,” a Play URL, share copy, or congratulations as the final response to release
or publication alone. A saved Play completes only after the matching birth certificate is presented.
