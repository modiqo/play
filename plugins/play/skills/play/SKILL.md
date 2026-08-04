---
name: play
description: >
  Use before tools or rote specialist skills when a user asks for an outcome that may be fulfilled
  by a reusable procedure. Search local and authorized Play indexes, run an adequate Play, or ask
  whether to explore with rote and preserve a new Play. Also use for daily or weekly Play digests,
  new and revised organization Plays, top public Plays, personal impact, explicit create-a-Play
  intent, or requests to search, list, inspect, run, create, save, share, and invite people to
  Plays, including work constrained to adapters, shell, browser, or combinations.
---

# Play

> Think in terms of Plays before thinking in terms of tools.

Treat `play` as the user-facing controller. Treat `rote-*` skills as internal execution owners.
Follow the declarative machine instead of reconstructing its lifecycle from prose.
Keep Play implicitly available at harness startup and invoke explicit-only rote specialists through
declared handoffs.

## Start or resume

1. Before the first Play task in a harness session, run `scripts/bin/play-preflight --harness
   <codex|claude|generic> --json`. Continue only when its `ready` field is true. If setup is
   required, show its harness-specific commands and stop; do not install Rote, authenticate, or
   alter the activation profile without the user's permission.
2. Read [references/controller/machine.yaml](references/controller/machine.yaml) on every activation.
3. Create a logical `play.context/v1` record in harness-owned thread/session state for a new task,
   or recover the existing logical record by task key or run ID.
4. Validate the context's machine version, current state, transition sequence, and pending action.
5. Execute exactly one declared prompt or entry action for the current state.
6. Accept only an event declared by the current state and validated by
   [references/controller/actions.yaml](references/controller/actions.yaml) or
   [references/controller/prompts.yaml](references/controller/prompts.yaml).
7. Evaluate guards, apply the declared mutation, checkpoint, and then enter the target state.
8. Repeat until `receipt`, `completed`, `exited`, or `blocked`.

Never jump states based on conversational intuition. Never infer completion from a specialist's
prose when its declared return event is absent or invalid.

## Own context without inventing storage

- Treat `play.context/v1` as a controller-state schema, not a storage protocol or authorization to
  write. Keep it in the current harness/thread state by default.
- Use a host-provided state or checkpoint API only when the host explicitly exposes and authorizes
  that mechanism for Play context.
- Never serialize Play controller context to an ad hoc file, including JSON or YAML under `/tmp`,
  `/private/tmp`, a repository, a home directory, or an execution workspace. Never invent a
  filename, database row, registry record, or other persistence backend for it.
- Interpret a state's `checkpoint` declaration as updating the logical context after or before a
  transition. It does not imply filesystem persistence.
- Reserve `execution.workspace` for approved Explore execution owned by a specialist; do not use
  it as a controller journal.
- Persist context only when the user explicitly requests it or a Play specification names the exact
  backend and ownership policy. If required state cannot otherwise be retained or recovered, enter
  `blocked` and report that missing capability instead of improvising storage.
- The on-demand digest store at `~/.rote/play/digest-state.json` is not controller context. It is a
  declared awareness cache containing only scope, SHA, and UTC checkpoint; do not add controller
  fields, digest cards, credentials, or registry payloads to it.

## Keep execution quiet

- Default user-facing updates to milestone-only: announce mode selection, approval gates, material
  effects, blockers, and terminal results, not every state transition, action, command, query, or
  response ID.
- Do not print internal context records, handoff packets, transition sequences, or rote evidence
  addresses unless the user asks for diagnostics or they are necessary to explain a blocker.
- Run an adequate existing registry Play through exactly one `rote play run` invocation and present
  its verified receipt. During Explore, keep result-dependent commands separate when correctness
  requires it, but do not narrate each command.
- For non-interactive rote execution, suppress optional CLI chatter when safe with
  `ROTE_FLOW_PROGRESS=0` and `ROTE_NO_HINTS=1`, and prefer summary or structured result modes.
  Never suppress primary payloads, errors, approval gates, effect disclosures, or receipts.
- Tool-call rendering is owned by the host UI, not this skill. Do not claim the skill can hide tool
  calls. A single visible execution requires a host-level Play runtime/tool that owns the machine;
  do not fake it by collapsing result-dependent or approval-gated actions into an unsafe shell
  chain.

## Make milestones feel alive

- For every user-visible milestone, resolve the current machine state through
  [references/integration/thinking-orbs.json](references/integration/thinking-orbs.json). Milestones
  remain mode selection, a search or run beginning, an approval gate, exploration beginning,
  crystallization/publication, a material blocker, and a terminal result—not every fast internal
  transition.
- A renderer is available only when the harness exposes a callable MCP Apps/custom-UI capability
  that accepts `play.presentation/v1`. Merely bundling `PlayActivity.tsx`, running in Codex or
  Claude terminal mode, or mentioning React is not renderer availability. Never claim an animated
  orb is visible without that callable capability.
- With a renderer, supply the resolved state, orb, message, accessible label, and terminal flag;
  do not print raw JSON. Without one, use the exact stdout of
  `scripts/bin/play-presentation <state>` as the first line of the milestone. It includes both the
  static orb glyph and message. Do not query the mapping with `jq`, copy only its `message`, omit the
  glyph, or call the fallback animated.
- For a prompt state, prefix the declared structured question with its exact listening fallback
  instead of sending a separate update. For a terminal state, make the exact terminal fallback the
  first line of the actual outcome and do not add a second celebratory line.
- Immediately before the single approved `rote play run`, present `use_run` once. Rote owns any
  progress it renders while that blocking command executes. Resume Play presentation only after the
  command returns and the machine enters its next milestone.
- Keep messages warm and brief, but never let whimsy obscure approval scope, writes, blockers,
  receipts, or the user's actual result. User-supplied tone and accessibility preferences win.

## Elicit choices through the harness

- Present every finite user decision as one well-formed question with explicit choices. Do not ask
  a bare yes/no or free-form question when the valid answers are already known.
- Use the harness's native structured elicitation control when available. Use single-select for
  mutually exclusive choices and multi-select for choices that can be combined.
- Give every choice a short label and one sentence describing its effect or tradeoff. Mark a
  recommendation only when Play can justify one from the request and policy.
- If the harness lacks the needed control, render the same choices as a numbered Markdown list and
  ask for one number or a comma-separated set of numbers. Preserve the prompt's declared event and
  payload regardless of presentation.
- Apply this contract to Play-owned prompts and delegated specialist questions. Include the prompt
  specification in the handoff instead of allowing a specialist to improvise a different choice.
- Use text elicitation for an open-ended outcome description. Keep its prompt id, input id, return
  event, and payload invariant across harnesses; use a direct Markdown question only as fallback.

## Load branch guidance

- Before `explore_route` or `explore_execute`, read
  [references/explore/modalities.md](references/explore/modalities.md).
- Before searching for Plays or presenting search results, read
  [references/awareness/search.md](references/awareness/search.md).
- Before `crystallize`, `save_offer`, authoring, publication, indexing, sharing, or invitation, read
  [references/publish/lifecycle.md](references/publish/lifecycle.md).
- Before preserving any irreducible inference step, read
  [references/explore/judge.md](references/explore/judge.md).
- Before organization summaries or Play listings, read
  [references/awareness/management.md](references/awareness/management.md).
- Before daily or weekly Play digests, new/revised Play awareness, public ranking, or personal
  impact summaries, read [references/awareness/digest.md](references/awareness/digest.md).
- Before recurring digest setup, scheduler discovery, delivery retry, or checkpoint release, read
  [references/integration/scheduling.md](references/integration/scheduling.md).
- Before presenting any finite choice, read
  [references/integration/elicitation.md](references/integration/elicitation.md).
- Before invoking a `rote-*` specialist, read
  [references/integration/rote-handoffs.md](references/integration/rote-handoffs.md).
- Before supplying progress state to a React-capable host UI, read
  [references/integration/thinking-orbs.md](references/integration/thinking-orbs.md) and use the
  exhaustive machine-state mapping in its adjacent JSON file. Never infer visual state from prose.

Do not load unrelated references.

## Search both Play sources

Use the bundled `scripts/bin/play-search` command for discovery. It normalizes unsafe natural-language
queries, searches local and authorized registry indexes concurrently, removes aliases and duplicate
versions by canonical Play reference, and emits canonical URIs, local-availability status, and
`rote play inspect` hints. Treat a
one-sided or malformed response as an incomplete search; never classify adequacy from partial
results.

For an explicit Find or Search request, present registry-addressable matches as structured choices.
If a match exists only in an authorized organization, say that a local pull/install is expected
before execution. Selecting a result authorizes read-only inspection only; it does not authorize a
pull, installation, repair, authentication, or run.

For a `run` request without a canonical reference, search by the recognizable name or outcome, then
inspect the selected match. If an apparently exact reference returns first-class `play-not-found`,
recover by searching its name once; do not treat authentication, malformed inspection data, or
other failures as permission to fall back.

## Build the habit loop

Keep Awareness, Use, and Explore distinct:

- Awareness is externally read-only. On an explicit digest request, use the remembered digest
  command: it may update only Play's local scope-keyed SHA and UTC checkpoint after presenting the
  result. When its comparison status is `unchanged`, say only that nothing changed and finish.
  Otherwise present new/revised authorized Plays and a truthfully labeled, explicitly scoped public
  ranking, then use the declared elicitation to Run, Search, Create, or finish. Never present
  organization-scoped lifetime downloads as a global or trending ranking.
- A Play selected from Awareness carries an exact canonical reference and displayed parameters into
  read-only inspection. Treat the selection as choosing what to inspect, never as execution approval.
- An explicit create-a-Play request enters creator discovery directly. Search existing Plays to
  avoid redundant creation; if a related Play exists, ask whether to Use, Adapt, or Create distinct.
- Explicit creator intent is Explore consent. Do not repeat the generic Explore-or-exit question,
  but preserve authentication, effect, modality widening, and publication gates.
- Recommend CALL for suitable adapters, SHELL for local work, and DRIVE for authenticated browser
  work. Present the recommendation as a milestone; ask only when policy requires a decision.

## Interpret decisions

Use agent reasoning only for the typed evaluators declared in `actions.yaml`:

- qualify the request;
- classify Play adequacy;
- classify creator reuse/adaptation options;
- select an allowed modality route;
- verify the requested outcome.

Return the evaluator's declared event and required payload. Explanation may accompany the payload,
but it cannot replace fields, add an event, select a target state, or override a guard.

Controller reasoning is not JUDGE. JUDGE exists only as a declared nondeterministic node inside a
saved Flow when the outcome itself cannot be reproduced deterministically.

## Preserve execution modes

For an adequate authorized match, enter Use:

```text
inspect → disclose → approve → rote play run → verify outcome → receipt → stop
```

Treat `rote play` as the first-class command surface for every Play operation it supports. Use
`rote play run <reference> [parameters]` for execution and `rote play inspect <reference> --json`
for inspection. Enter `rote flow` or `rote registry flow` only for a capability that `rote play`
does not expose, such as current search, listing, authoring, or publication gaps. A failed
`rote play` command is not a capability gap and never authorizes a lower-level fallback.
Keep every lower-level use scoped to that missing operation and return to `rote play` as soon as a
canonical Play reference exists. Explore may use Flow tooling only while no first-class Play
operation can represent the unfinished candidate.

`rote play run` already verifies, installs, converges adapters and credentials, checks dependencies
and Flow validity, and runs the exact prepared Flow. Do not reproduce its internals with
`rote registry flow pull`, `rote flow run`, adapter setup, or manual preflight—even when the Play
is already local.

Before every run, invoke `scripts/bin/play-inspect <reference> --json`. This reusable wrapper uses
`rote play inspect <reference> --json` and performs no pull, installation, repair, authentication,
or execution. Present, compactly:

- the exact resolved version, visibility, description, and parameters;
- whether the Play is present, absent, stale, or needs replacement locally;
- required adapters, runtimes, packages, browser capabilities, credentials, and current host checks;
- declared steps and service operations, declared write permissions, and sensitivity;
- blockers and any effect uncertainty. Generic adapter `exec` steps do not prove read-only external
  behavior, so say that their read/write semantics are unknown unless the manifest declares them.

Then use the `approve_play_run` structured prompt. A user request containing “run”, an exact
reference, displayed parameters, an Awareness choice, or a search choice identifies what to inspect;
none is post-inspection approval. Use `--yes` only after the approval event binds the exact resolved
reference, displayed parameters, and inspection SHA. If any of them change, inspect and ask again.
Never pipe input to automate a selector. If `rote play run` fails, report its failure or enter the
declared repair path without decomposing the command.

For partial, uncertain, or absent matches, ask whether to Explore with rote or continue normally.
Do not execute an exploration modality before approval. If the user continues normally, enter
`exited`, suppress Play re-entry for the same task, and let the ordinary harness proceed.

## Respect policy

- Treat user modality constraints as authoritative.
- Ask before widening CALL, SHELL, or DRIVE.
- Keep JUDGE forbidden unless the policy allows it.
- Keep writes and human gates visible in the delegated runtime.
- Verify the requested outcome before preparing a candidate.
- Ask Private, Public, or Skip only after candidate preparation.
- Treat Private and Public as authorization to author, release, and publish with that visibility.
- Treat Skip as unpublished local exploration state, not a saved Play.
- Treat private as registry-backed organization ownership, never merely a local file.
- Index the exact canonical version after successful Private or Public publication.
- After indexing, run `rote play inspect <org/name> --json` against the canonical reference.
  Verify its owner, version, and visibility, show a compact JSON-backed success readout, and
  congratulate the user only after that readback matches the authorized publication.

## Delegate execution

For first-class `rote play` operations, invoke that controller directly. For unsupported operations
that require a specialist, build the normalized packet in
[references/integration/rote-handoffs.md](references/integration/rote-handoffs.md), select one existing owner, and require
its declared return event. Specialists own gap commands and evidence capture; Play owns consent,
policy, transitions, and user-facing closure.

Do not restart the top-level `rote` skill router after Play search. Enter the selected gap
specialist directly so search and Explore consent occur exactly once. This restriction never
applies to the first-class `rote play` CLI surface.

## Stop safely

Enter `blocked` when an action or evaluator returns invalid output, authority is missing, a required
modality remains forbidden, an unsafe effect lacks approval, the exploration budget is exhausted,
or machine state cannot be recovered. Report the blocker and evidence without inventing defaults.

At terminal state, present only the outcome relevant to that terminal:

- `receipt`: verified unchanged Use result;
- `completed`: verified Explore result plus saved reference or explicit unpublished status;
- `completed` for a saved Play: verified result, matching inspect readout, and a brief
  congratulations;
- `completed` for management: the requested organization summary or grouped Play inventory;
- `completed` for awareness: the requested digest and the user's declared dismissal or follow-up;
- `exited`: confirmation that Play stepped aside for this task;
- `blocked`: missing authority, capability, valid output, or recoverable state.
