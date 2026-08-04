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

1. Read [references/controller/machine.yaml](references/controller/machine.yaml) on every activation.
2. Create a logical `play.context/v1` record in harness-owned thread/session state for a new task,
   or recover the existing logical record by task key or run ID.
3. Validate the context's machine version, current state, transition sequence, and pending action.
4. Execute exactly one declared prompt or entry action for the current state.
5. Accept only an event declared by the current state and validated by
   [references/controller/actions.yaml](references/controller/actions.yaml) or
   [references/controller/prompts.yaml](references/controller/prompts.yaml).
6. Evaluate guards, apply the declared mutation, checkpoint, and then enter the target state.
7. Repeat until `receipt`, `completed`, `exited`, or `blocked`.

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
  `ROTE_FLOW_PROGRESS=0` and `rote_NO_HINTS=1`, and prefer summary or structured result modes.
  Never suppress primary payloads, errors, approval gates, effect disclosures, or receipts.
- Tool-call rendering is owned by the host UI, not this skill. Do not claim the skill can hide tool
  calls. A single visible execution requires a host-level Play runtime/tool that owns the machine;
  do not fake it by collapsing result-dependent or approval-gated actions into an unsafe shell
  chain.

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
- Before presenting any finite choice, read
  [references/integration/elicitation.md](references/integration/elicitation.md).
- Before invoking a `rote-*` specialist, read
  [references/integration/rote-handoffs.md](references/integration/rote-handoffs.md).

Do not load unrelated references.

## Search both Play sources

Use the bundled `scripts/bin/play-search` command for discovery. It normalizes unsafe natural-language
queries, searches local and authorized registry indexes concurrently, removes aliases and duplicate
versions by canonical Play reference, and emits canonical URIs plus `rote play run` hints. Treat a
one-sided or malformed response as an incomplete search; never classify adequacy from partial
results.

## Build the habit loop

Keep Awareness, Use, and Explore distinct:

- Awareness is read-only. Collect a complete digest, present new/revised authorized Plays and a
  truthfully labeled, explicitly scoped public ranking, then use the declared elicitation to Run,
  Search, Create, or finish. Never present organization-scoped lifetime downloads as a global or
  trending ranking.
- A Play selected from Awareness carries an exact canonical reference and displayed parameters.
  Treat that structured selection as the approval for the corresponding `rote play run ... --yes`.
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
rote play run → verify outcome → receipt → stop
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

When the user explicitly requests an exact Play reference and parameters, run
`rote play run <reference> [parameters] --yes`; that request is the exact approval represented by
`--yes`. Otherwise obtain structured approval for the displayed reference and parameters before
using `--yes`, or allow the controller's Ready selector. Never pipe input to automate that selector.
Use `rote play inspect` before a run only for an explicit inspection request or when its read-only
details are required to form an approval question. If `rote play run` fails, report its failure or
enter the declared repair path without decomposing the command.

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
