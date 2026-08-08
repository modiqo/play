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

Play's typed runtime owns the controller. The model handles only declared evaluator, prompt,
approval, presentation, and specialist boundaries. Do not reconstruct or reread the complete state
machine during a run.

## Enter or resume the runtime

For a new task, call:

```text
scripts/bin/play-machine run-until-yield --stdin --json
```

with a nonempty harness-owned run ID, stable task key, and the unchanged user request:

```json
{"run_id":"<run-id>","task_key":"<task-key>","request":{"original":"<request>"}}
```

The command creates the complete logical `play.context/v1`, executes eligible deterministic
actions, validates every event, applies context fields, checkpoints the transition, and stops only
at a boundary requiring model, user, or specialist work. Retain its `session_token` opaquely in
harness/thread state. To resume, call the same command with `session_token` and the one declared
event:

```json
{"session_token":"<opaque-token>","event":{"id":"<event>","payload":{},"guards":{}}}
```

Never decode, edit, summarize, or manufacture the token. Never serialize Play controller context to an ad hoc file. A token is an in-thread transport envelope, not authorization for persistence. Do
not write it under `/tmp`, a repository, a home directory, a registry, or an execution workspace.
If the harness cannot retain the token, emit `action_blocked` and stop.

The returned projection is the entire current instruction contract. It contains the current state,
boundary, minimum input, exact action or prompt, and accepted event payloads. Do not read
`machine.yaml`, `actions.yaml`, `prompts.yaml`, or `context.schema.json` during a normal run. The
runtime already loaded, validated, and bundle-hash-bound them.

## Handle each yield

Follow only the returned `projection.state.boundary`:

- `evaluator_action`: reason over only `instruction.input`, policy, and accepted events. Return one
  declared event with every required payload field. Evaluators are limited to request qualification,
  adequacy, creator reuse, route selection, and outcome verification.
- `prompt`: present the exact projected prompt through the harness's structured elicitation control.
  Read [references/integration/elicitation.md](references/integration/elicitation.md) immediately
  before the prompt. Resume with the selected declared event and bound values.
- `delegated_action`: read [references/integration/rote-handoffs.md](references/integration/rote-handoffs.md),
  invoke only the projected specialist owner, and resume only with its typed receipt event.
- `deterministic_action`: the runtime yielded because the action is effectful, owned by another
  runtime, or lacks a safe automatic adapter. Execute exactly the projected command or declared
  owner contract. Do not improvise a fallback. Resume with one accepted typed event.
- `terminal`: present only the terminal outcome described below and stop.

Pass returned `presentations` to the user in order before handling the final boundary. They are
complete milestone presentations, not debug output. Do not print the session token, raw context,
transition record, command chatter, or evidence addresses.

If `instruction.preflight_required_for_events` contains the evaluator event you selected, run
`scripts/bin/play-preflight --harness <codex|claude|generic> --json` after qualification and before
resuming. Include `"preflight":{"ready":true}` with the resume request. Conversation and excluded
repository work exit without paying this probe. If setup is required, invoke the callable
`rote-setup` skill; Play never installs or authenticates Rote itself.

## Keep execution quiet and visible at milestones

Default to milestone-only updates: mode selection, search/run beginning, approval, exploration,
save/publication, blockers, and terminal results. Do not narrate fast deterministic transitions.
For non-interactive Rote execution, set `ROTE_FLOW_PROGRESS=0` and `ROTE_NO_HINTS=1` when safe, but
never suppress primary output, errors, approvals, effects, references, or receipts.

For every visible milestone, resolve the projected state through
`scripts/bin/play-presentation <state>`. A renderer exists only when the harness exposes a callable
custom UI accepting `play.presentation/v1`. Merely bundling `PlayActivity.tsx`, using a terminal
harness, or mentioning React is not renderer availability. Without a renderer, use the exact stdout
as the first line; it contains the static orb glyph and message. Do not query the mapping with `jq`,
copy only the message, or call the fallback animated. For prompts, prefix the structured question
with the listening fallback. For terminals, use the terminal fallback as the first line of the
actual outcome.

Immediately before an approved `rote play run`, present `use_run` once. After execution, preserve
the complete detailed primary payload and route it through the projected `use_output` action before
verification. Compact summaries are incomplete results.

## Load only branch guidance returned by the trajectory

Read a branch reference only immediately before its boundary:

- Search, results, or adequacy: [references/awareness/search.md](references/awareness/search.md)
- Explore route or execution: [references/explore/modalities.md](references/explore/modalities.md)
- Irreducible saved inference: [references/explore/judge.md](references/explore/judge.md)
- Save, author, publish, index, share, or invite: [references/publish/lifecycle.md](references/publish/lifecycle.md)
- Birth capture, binding, lookup, or certificate: [references/publish/birth.md](references/publish/birth.md)
- Organization summaries or inventory: [references/awareness/management.md](references/awareness/management.md)
- Digest or public awareness: [references/awareness/digest.md](references/awareness/digest.md)
- Recurring delivery: [references/integration/scheduling.md](references/integration/scheduling.md)
- First-use orientation: [references/onboarding/first-use.md](references/onboarding/first-use.md)
- Callable Rote specialist handoff: [references/integration/rote-handoffs.md](references/integration/rote-handoffs.md)

Do not load unrelated references. The runtime projection already carries the state-local command
policy from `actions.yaml` or the exact structured prompt from `prompts.yaml`.

## Preserve the Use contract

An adequate authorized Play follows:

```text
inspect → disclose → approve → rote play run → detailed output → verify → receipt
```

Use `scripts/bin/play-inspect <reference> --json` for read-only inspection and
`rote play run <exact-reference> <approved-parameters> --yes` only after the exact post-inspection
approval event. A request containing “run,” a URI, a search selection, or displayed parameters
selects what to inspect; it is never execution approval. If reference, parameters, or disclosure
SHA changes, inspect and ask again.

`rote play run` owns installation, convergence, dependencies, credentials, and execution. Never
decompose it into registry pull, adapter setup, or lower-level commands. A failed `rote play` command is not a capability gap and never authorizes a legacy or manual fallback.

Present the resolved version, visibility, description, parameters, local status, dependencies,
credentials by name, operations, declared writes, blockers, and uncertainty. Generic adapter
operations do not prove read-only behavior. Never pipe input to automate a selector.

## Preserve Awareness and onboarding

Search both local and authorized registry indexes only through `scripts/bin/play-search`; require a
complete two-source response, normalized canonical references, and deduplicated versions. A result
selection authorizes inspection only. An authorized organization-only result may require a local
pull during an approved run.

Digest requests use `scripts/bin/play-digest --remember`; its local cache stores only scope, SHA,
and UTC checkpoint. When unchanged, say only “Nothing new since your last Play check.” Otherwise
present the grouped Play inbox and truthfully labeled public-card lifetime metrics, never a false
time-window trend.

An empty `$play` or `/play` and a canonical `https://play.modiqo.ai/<owner>/<name>` URI use the typed
onboarding trajectory. Missing Rote delegates to `rote-setup`. A URI without Rote may fetch only the
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

CALL must search installed adapters and then the Rote catalog before documentation discovery. Show
all catalog choices and never silently collapse REST and MCP entries. Authentication repair must
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
