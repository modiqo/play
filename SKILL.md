---
name: play
description: >
  Use before tools or rote specialist skills when a user asks for an outcome that may be fulfilled
  by a reusable procedure. Search local and authorized Play indexes, run an adequate Play, or ask
  whether to explore with rote and preserve a new Play. Also use for daily or weekly Play digests,
  new and revised organization Plays, top public Plays, personal impact, explicit create-a-Play
  intent, owner-local Play birth certificates, or requests to search, list, inspect, run, create,
  save, share, show how a Play was born, and invite people to
  Plays, including work constrained to adapters, shell, browser, or combinations. Also use for
  empty `$play` or `/play` invocations and bare or prefixed public Play URIs.
---

# Play

> Think in terms of Plays before thinking in terms of tools.

Treat `play` as the user-facing controller. Treat `rote-*` skills as internal execution owners.
Follow the declarative machine instead of reconstructing its lifecycle from prose.
Keep Play implicitly available at harness startup and keep all rote specialists model/harness-
invocable so declared handoffs can chain without requiring another user command.

## Start or resume

1. Enter the deterministic `invoke` state before model qualification. It recognizes only an empty
   `$play` or `/play`, a bare or prefixed canonical `https://play.modiqo.ai/<owner>/<name>` URI, or
   an ordinary request. For an ordinary request, run `scripts/bin/play-preflight --harness
   <codex|claude|generic> --json` before continuing. Empty and URI invocations use the typed live
   onboarding probe instead, because missing Rote is a declared setup/card branch rather than an
   early preflight exit.
2. Read [references/controller/machine.yaml](references/controller/machine.yaml) on every activation.
3. Create a logical `play.context/v1` record in harness-owned thread/session state for a new task,
   or recover the existing logical record by task key or run ID. Initialize `output_policy` to
   detailed mode, human presentation, a 200,000-byte inline limit, and artifact overflow; initialize
   the `output` record with null result fields, empty manifest lists, and `truncated: false`.
   Initialize `adapter_discovery` with `status: unknown`, a null query and selected id, and empty
   searched-source, choice, and evidence lists. Initialize `publication_validation` with credential
   and smoke statuses set to `not_required`, empty adapter contracts and evidence, null references,
   digests, byte counts, and timings, and `isolated_workdir: false`. Initialize `onboarding` with
   `intent`, Rote, and identity statuses set to `unknown`; setup status `not_required`; null command,
   email, handle, URI, card, references, and timings; false off-PATH/presented flags; and empty
   evidence.
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
- The owner-private birth store at `~/.play/births` is also not controller context. It is an
  explicitly declared content-addressed store for redacted birth objects and URI bindings only.
  Never put pending actions, consent, harness state, credentials, or raw workspace evidence in it.

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
  `ROTE_FLOW_PROGRESS=0` and `ROTE_NO_HINTS=1`. Never request summary output for a Play run.
  Prefer Rote's human presentation when available; otherwise accept JSON or structured responses
  only when they preserve the complete primary payload. Never suppress primary payloads, errors,
  approval gates, effect disclosures, full-output references, or receipts.
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
- After the run, pass its complete payload through `use_output` before verification. Render the
  detailed result first with stable Markdown formatting, then its response references, artifact
  references, effects, and receipt. A compact summary is an incomplete result, not a successful
  terminal presentation.
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
- Before birth capture, URI binding, lookup, or verification, read
  [references/publish/birth.md](references/publish/birth.md).
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

## Welcome and URI onboarding

Keep this trajectory fully typed and live-probed:

- A trimmed `$play` or `/play` with no arguments enters `onboarding_probe`. Check PATH first, then
  `~/.local/bin/rote` and `~/.cargo/bin/rote`; do not infer installation from memory or `~/.rote`.
- When Rote is installed, enter `onboarding_identity` and run exactly one resolved-binary
  `whoami`. Extract the authenticated email and local-part handle, retain only a digest of raw
  output, then ask the templated text prompt: “How are you, `<handle>`? What can I help you with?”
  Route its answer back through `invoke`; do not assume every answer is an outcome request.
- If Rote is absent or `whoami` is not authenticated, invoke the callable `rote-setup` skill. That
  specialist owns sequential live probing, install choices, remote-code approval, login, and
  optional onboarding. Play must not run an installer or login itself. After a successful return,
  re-enter `onboarding_probe` and independently verify binary and identity state.
- A canonical Play URI with installed Rote enters the existing `use_inspect` state and therefore
  uses `scripts/bin/play-inspect`, backed by `rote play inspect`. Inspection remains read-only and
  run approval remains a separate prompt.
- A canonical Play URI without Rote enters `onboarding_card_fetch`. Curl only the exact HTTPS
  `play.modiqo.ai` owner/name URI, without redirects, credentials, cookies, or custom headers.
  Require a matching bounded `rote.play.v1` JSON card whose inspect action is read-only. Present
  its description, parameters, adapter and credential names, effects, inspect command, and its own
  consent-gated install/bootstrap links. Never execute those actions or claim local inspection.
- Reject other hosts, schemes, credentials-in-URL, ports, queries, fragments, malformed cards, or
  mismatched card identities. Send nonempty non-URI invocations unchanged to normal qualification.

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
  result. Treat “whats new”, “what's new”, “anything new in Plays”, “catch me up on Plays”, and the compact
  `$play digest` alias as the same awareness intent. Frame the result as a Play inbox. When its
  comparison status is `unchanged`, say only “Nothing new since your last Play check.” and finish.
  Otherwise group new/revised authorized Plays by organization and show title, publication author
  when available, short description, visibility, timestamp, and canonical reference. Follow with
  the top 10 authorized public Plays using the truthfully labeled available metric, then use the
  declared elicitation to Run, Search, Create, or finish. Never present
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
When the likely route includes DRIVE and the outcome depends on extracting page content beyond the
canonical typed slices, include the DRIVE crystallization limit from
[references/explore/modalities.md](references/explore/modalities.md) in the Explore offer, so the
user knows before consenting that the result may not be preservable as a `rote play run`-eligible
Play. Do not execute an exploration modality before approval. If the user continues normally, enter
`exited`, suppress Play re-entry for the same task, and let the ordinary harness proceed.

## Respect policy

- Treat user modality constraints as authoritative.
- Ask before widening CALL, SHELL, or DRIVE.
- Keep JUDGE forbidden unless the policy allows it.
- Treat adapter probe hints, including `readOnlyHint` and `destructiveHint`, as discovery and
  disclosure metadata only. Never turn a hint into an approval gate, blocker, or confirmation.
- Keep writes and human gates visible in the delegated runtime.
- Verify the requested outcome before preparing a candidate.
- Ask Private, Public, or Skip only after candidate preparation.
- Treat Private as authorization to author, release, and publish with that visibility. Treat Public
  as authorization to do the same, verify associated adapter credential contracts, and execute the
  exact versioned public URI once with the verified parameters from an isolated `/tmp` directory.
- Treat Skip as unpublished local exploration state, not a saved Play.
- Treat private as registry-backed organization ownership, never merely a local file.
- After release and before publication, capture the one-time owner-private birth object. After
  publication and before indexing, bind it to the minted exact reference and registry content hash.
  These writes are authorized parts of the declared save lifecycle; they never publish the birth.
- Index the exact canonical version after successful Private or Public publication.
- After indexing, run `rote play inspect <org/name> --json` against the canonical reference.
  Verify its owner, version, and visibility. For Public, compare every associated selected adapter
  with `rote adapter info` and `rote registry adapter info`: require receipt-verified provenance and
  matching source, version, fingerprint, auth family, and credential environment-variable names.
  Never read or retain credential values. Fingerprint equality alone is insufficient.
- After the public credential contract matches, run exactly one
  `rote play run <registry-returned-versioned-uri> <verified-parameters> --yes` from a fresh
  temporary directory under `/tmp`. Preserve only status, bounded metadata, digests, byte count,
  and latency—not the smoke run's primary payload. This verifies canonical resolution and the
  current host's credential readiness; it does not prove every consumer is configured. On any
  mismatch or failure, block presentation and leave repair, authentication, pull, and cleanup to
  their Rote owners.
- Only after the matching readback and, for Public, successful contract and smoke gates, show the
  compact JSON-backed success readout and congratulate the user. Present the exact registry-returned Play page URI and
  install/bootstrap URI, a clickable Play link labeled with its title and description, and fenced
  plain-text copy ready to paste into X and LinkedIn. Keep X within 280 characters and include the
  Play URI in both blocks. Never reconstruct or omit returned URLs, and never post the copy without
  a separate explicit request.

## Delegate execution

For first-class `rote play` operations, invoke that controller directly. For unsupported operations
that require a specialist, build the normalized packet in
[references/integration/rote-handoffs.md](references/integration/rote-handoffs.md), select one existing owner, and require
its declared return event. Specialists own gap commands and evidence capture; Play owns consent,
policy, transitions, and user-facing closure.

Treat specialist dispatch as fail-closed. `CALL` means `rote-using-adapters`, `SHELL` means
`rote-shell`, `DRIVE` means `rote-browse`, and combined routes mean `rote-workspace`. Before
`explore_execute`, enter `explore_handoff`, enumerate the rote-* skills actually exposed as callable
by this harness, and prepare the typed packet with `scripts/bin/play-handoff prepare --stdin --json`.
An installed skill file, MCP server, app, shell, or browser tool is not proof that the selected
specialist is callable. If the exact owner is unavailable, emit `specialist_unavailable` and block.

During `explore_execute`, never call MCP, app, shell, or browser tools directly. Invoke only the
selected rote-* skill through the harness skill mechanism. Route its response through
`explore_receipt` and `scripts/bin/play-handoff verify --stdin --json`; accept `outcome_ready` or
`route_exhausted` only with a matching `play.handoff-receipt/v1`. A Rote
`confirmation_required` result must likewise arrive as the typed receipt event, then enter
`effect_offer`; Play may not infer that event from probe annotations. A raw tool result, prose
response, wrong owner, mismatched packet, or missing receipt must block and can never satisfy
Explore.

A recoverable CALL authentication failure must arrive as the typed `auth_repair_required` event;
Play does not classify or execute the repair. After explicit approval, prepare a separate
`play.auth-repair-handoff/v1` packet for `rote-adapter-config`, validate its matching repair receipt,
then create a fresh execution packet for the original execution owner. Preserve the
original operation inputs and idempotency key, bind the retry to the validated repair receipt, and
still require the original CALL and outcome verification. Decline, an unavailable repair owner, a
failed repair, or an invalid receipt blocks without running the provider operation. Never place raw
credentials in Play context or either handoff packet.

When `effect_offer` is entered, surface the exact Rote-provided tool, impact, confirmation token,
workspace, and evidence. Approval must bind those exact fields, invalidate the old handoff packet,
and prepare a new packet that tells the same specialist to resume the same workspace and retry only
the guarded call with `--confirm <token>`. Declining blocks without performing the effect. Do not
independently classify, weaken, strengthen, or synthesize the guard.

For a CALL route, enter `explore_dispatch`, then `adapter_discover` before preparing the execution
handoff. Ask `rote-adapter-create` to search installed adapters first. If none adequately covers the
capability, it must run `rote adapter catalog search <adapter_discovery.query> --json`. Present every
catalog match through `adapter_offer`; never silently choose one, collapse REST and MCP entries for
the same provider, or continue to provider documentation while catalog matches remain. Only a
successful zero-result catalog search or the user's explicit rejection permits supplied-spec or
provider-document discovery. Bind the chosen or exhausted discovery record into the CALL packet.

After discovery, make Rote adapter convergence part of the delegated execution handoff. Reuse the
selected installed adapter or delegate creation to `rote-adapter-create`; it determines from the
selected catalog entry, supplied spec, endpoint, server card, or provider documentation whether the
substrate is OpenAPI, GraphQL, or MCP, then uses the matching Rote creation path. Delegate initial
authentication during creation to `rote-adapter-create`. For a recoverable authentication failure from an existing
CALL packet, use the dedicated approved `rote-adapter-config` repair handoff above, preserve its
human approval gates, and keep secret entry masked. Only then execute through
`rote-using-adapters`. Specs, endpoint metadata,
documentation, and MCP server cards may support type discovery; invoking the provider capability
directly may not. A successful CALL receipt must carry the adapter id, detected substrate and
evidence, creation/reuse provenance, auth provenance, and `direct_tool_execution=false`; otherwise
block.

Do not restart the top-level `rote` skill router after Play search. Enter the selected gap
specialist directly so search and Explore consent occur exactly once. This restriction never
applies to the first-class `rote play` CLI surface.

## Stop safely

Enter `blocked` when an action or evaluator returns invalid output, authority is missing, a required
modality remains forbidden, an explicit Rote `confirmation_required` effect is declined or lacks
approval, the exploration budget is exhausted, or machine state cannot be recovered. Probe hints
alone never satisfy this condition. Report the blocker and evidence without inventing defaults.

At terminal state, present only the outcome relevant to that terminal:

- `receipt`: verified unchanged Use result;
- `completed`: verified Explore result plus saved reference or explicit unpublished status;
- `completed` for a saved Play: verified result, matching inspect readout, and—when Public—verified
  associated adapter credential contracts, a successful isolated canonical URI smoke run with
  measured latency, the Play page, install/bootstrap link, and paste-ready X and LinkedIn copy,
  followed by a brief congratulations;
- `completed` for management: the requested organization summary or grouped Play inventory;
- `completed` for birth lookup: the requested owner-local certificate or an honest absent/ambiguous
  result;
- `completed` for awareness: the requested digest and the user's declared dismissal or follow-up;
- `exited`: confirmation that Play stepped aside for this task;
- `blocked`: missing authority, capability, valid output, or recoverable state.
