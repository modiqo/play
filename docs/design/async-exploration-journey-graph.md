# Asynchronous exploration Journey Graph

- **Status:** Foundation implemented on `design/async-exploration-journey-graph`
- **Scope:** Captured Play exploration only
- **Owners:** Play semantic layer; Rote remains the execution and evidence substrate
- **Target schema:** `play.journey-graph/v1`
- **Primary constraint:** Journey construction must not slow harness inference, tool use, or response delivery

## Summary

Play should maintain an owner-private semantic graph for every captured exploration. The graph
groups Rote's operational workspace history (`@1`, `@2`, dependency edges, failures, timings, and
token accounting) into human work such as discovering a capability, connecting a service,
retrieving data, recovering from failure, verifying an outcome, and producing an artifact.

The semantic graph is a **projection**, not a replacement for the Rote workspace:

```text
Rote workspace                         Play Journey Graph
--------------                         ------------------
lossless operational evidence          human-semantic projection
commands and @N responses              intent, phases, decisions, authority
field-level dependencies               effects, evidence, artifacts, recovery
timings and token accounting           progress and crystallization structure
authoritative and replayable           disposable and rebuildable
```

Journey construction runs outside the foreground interaction path. Capture start launches a
short-lived, low-priority worker. The worker observes workspace changes, reads Rote's existing JSON
surfaces, classifies and groups the new activity, and atomically replaces a bounded snapshot.
Foreground hooks never invoke Rote for Journey rendering. They perform at most one bounded snapshot
read and remain silent when no fresh semantic milestone is available.

The same snapshot can support compact chat pulses, a live terminal, a future graphical renderer,
and crystallization. A projection failure must never interrupt exploration or invalidate Rote
evidence.

## Motivation

Rote already persists the operational trajectory and constructs a dependency DAG. Play currently
projects an exploration pulse by invoking `rote workspace stats --json` and parsing the human
output of `rote trace --deps`. The pulse shows recent `@N` operations and a few raw dependency
edges. That is useful for debugging but does not answer the questions a person has during work:

- What outcome are we pursuing?
- Which meaningful phase is active?
- What has been established or produced?
- Why are we blocked?
- What decision or authority is required from me?
- Which failure was recovered, and how?
- Which part of this journey is likely reusable?

Rendering a larger raw DAG would amplify the problem. The missing layer is semantic compression:
many operational activities should support one human-meaningful node while remaining available for
creator inspection and audit.

## Goals

1. Build a durable semantic projection of captured exploration while work is in progress.
2. Preserve a direct evidence link from every semantic claim to Play events, Rote command
   sequences, and Rote response references.
3. Keep all expensive ingestion, classification, grouping, and compaction off the foreground
   harness path.
4. Render only meaningful changes at normal chat boundaries; never inject asynchronous chatter
   into an active inference.
5. Make the graph useful as the intermediate representation for crystallization.
6. Keep Rote authoritative and permit complete Journey reconstruction after worker failure,
   upgrade, or classifier changes.
7. Protect credentials, response bodies, sensitive parameters, and workspace paths.
8. Require no Rote changes for the first implementation.

## Non-goals

- Replacing Rote's workspace, dependency graph, replay, export, or token accounting.
- Showing every command or response as a human-visible node.
- Parsing or storing raw response bodies in the Play state directory.
- Asking another model to classify every tool call.
- Making Journey availability a prerequisite for exploration, verification, settlement, or Play
  execution.
- Building the graphical cartography renderer in this phase.
- Capturing `direct:` work as verified Rote evidence.
- General agent observability outside an active Play capture.

## Design principles

### Rote owns truth; Play owns meaning

Rote answers what executed, which response was produced, and how data moved. Play answers what
that evidence means within the user's outcome. Play may interpret evidence but cannot rewrite it or
promote an unsupported claim to verified.

### Semantic claims are evidence-bound

A completed semantic node must name its supporting sources. Planned nodes may lack evidence;
satisfied and verified nodes may not.

### Projection is expendable

Deleting the Journey directory must not delete work or make the capture unverifiable. The worker
can rebuild the projection from the Play capture record, Play lifecycle events, and Rote workspace.

### The foreground is snapshot-only

No hook that participates in prompt submission, response completion, or inference continuation may
run `rote`, inspect SQLite, classify operations, wait for a worker, or acquire the writer lease.

### Semantic progress, not telemetry

Chat renders state changes such as “Gmail connected” or “Receipt totals verified.” It does not
render command counts merely because more commands were recorded. Latency and token measurements
remain available as secondary telemetry.

### Model suggestions never establish runtime fact

A model may propose labels, grouping, or candidate phase boundaries. Deterministic validation
establishes membership, operation success, authority state, and verification.

## Existing data surfaces

The initial implementation consumes only supported Rote CLI surfaces from the bound workspace:

```text
rote workspace inspect log --json
rote workspace inspect deps --json
rote workspace stats --json
```

`rote trace --deps` remains useful for humans but has no JSON flag and must not be the Journey
compiler's machine contract.

The command log currently supplies sequence, command type, encoded command parameters, response
IDs, timestamps, and export status. Command parameters can carry structured adapter/tool identity,
process invocation metadata, and process-policy decisions. The dependency surface supplies source
response, target command, dependency type, source query, and target field. Stats supply aggregate
counts and token savings.

The worker may inspect response envelope metadata needed to determine status, duration, and a
bounded output shape. It must not copy response payloads into the Journey store.

## Sources composed by Play

The Journey is not merely a Rote projection. It joins four event families:

1. **Play lifecycle:** intent accepted, capture created, search exhausted, prerequisite ready,
   refinement accepted, outcome verified, save decision, candidate created, release, publication.
2. **Human decisions:** selected capability, supplied parameter, approved effect, chose recovery,
   redirected the goal, or declined a branch.
3. **Rote evidence:** command sequences, response references, dependency edges, status, timing,
   token accounting, adapters, tools, and processes.
4. **Typed receipts:** authentication, effect approval, output verification, artifacts,
   crystallization, and publication evidence.

A meaningful node such as “Confirm date range” can exist entirely in Play. A node such as
“Retrieve matching messages” can group dozens of Rote operations. A node such as “Receipt report”
can join Rote evidence to a Play verification receipt.

## Architecture

```text
                     foreground interaction path

 user/harness ──► Play machine ──► Rote specialist ──► result
       │               │                                      │
       │               └── append bounded Play event          │
       │                                                      │
 Stop hook ── read latest snapshot only                       │
       ▲                                                      │
       │ atomic snapshot                                      │
       │                                                      ▼
 ┌──────────────────── asynchronous projection plane ────────────────┐
 │                                                                  │
 │  capture worker ──► workspace fingerprint changed?               │
 │       │                         │                                 │
 │       │ no: back off           └─ yes                            │
 │       │                              │                            │
 │       │       Rote JSON ingestion ◄──┘                            │
 │       │                │                                         │
 │       │         normalize activities                             │
 │       │                │                                         │
 │       │       deterministic classification                       │
 │       │                │                                         │
 │       │        DAG motif segmentation                            │
 │       │                │                                         │
 │       │        merge Play events/receipts                        │
 │       │                │                                         │
 │       └──────► append event log + replace snapshot                │
 │                                                                  │
 └──────────────────────────────────────────────────────────────────┘
```

### Capture-scoped worker

Capture creation starts one detached worker for the bound workspace. It is not a globally installed
daemon and requires no `launchd`, `systemd`, or login item.

The worker:

- acquires a capture-scoped single-writer lease;
- lowers its scheduling priority where the platform supports it;
- fingerprints the workspace database, WAL, response directory, and Play event spool using file
  metadata before invoking any Rote command;
- coalesces bursts of changes;
- backs off while the workspace is idle;
- exits when the capture becomes terminal or after a bounded idle timeout;
- can be safely restarted because projections are idempotent and rebuildable.

Only one worker may write a Journey. A duplicate launcher observes the live lease and exits.

### Foreground wake behavior

Capture start is the primary worker launch point. A response-completion hook may notice a missing or
expired worker lease and schedule a detached restart, but it must not wait for process startup. It
may append or touch a constant-size wake marker using atomic filesystem operations.

The foreground path performs no workspace scan and no subprocess execution.

### Change detection and polling

The first portable implementation uses metadata polling rather than platform-specific file-system
watch APIs:

```text
active change burst:  250–500 ms coalescing window
active workspace:     1 second poll
idle backoff:          2 s → 5 s → 15 s
terminal/idle:         worker exits
```

The worker invokes the Rote JSON surfaces only when the workspace fingerprint advances. File-system
watchers may be added later behind the same interface.

### Event log and snapshot

Suggested owner-private layout:

```text
~/.rote-play/journeys/<journey-id>/
  events.jsonl
  journey.sqlite3
  snapshot.json
  worker.json
  lease
```

`events.jsonl` is append-only-in-meaning. It contains normalized, privacy-bounded Play lifecycle
events, not raw Rote payloads. `journey.sqlite3` is the complete canonical semantic projection: it
retains every normalized activity, dependency, semantic node, edge, and evidence mapping without
pruning. `snapshot.json` is only a bounded foreground viewport atomically replaced by the worker;
it declares whether it is complete and reports the canonical node/edge totals. `worker.json`
contains safe generation and health metadata. The lease is ephemeral.

All durable files are mode `0600`; directories are `0700`. The opaque Journey ID is bound to the
owner-private capture record. User-facing output never prints the ID or workspace path.

## Semantic model

### Node kinds

The initial closed vocabulary is:

| Kind | Meaning |
|---|---|
| `intent` | The user's desired outcome. |
| `phase` | A meaningful unit of outcome-bearing work. |
| `capability` | A selected Play, adapter, browser, CLI, API, or other ability. |
| `decision` | A human choice, parameter, refinement, or route selection. |
| `authority` | Authentication, scope, approval, or effect authorization. |
| `effect` | An external read/write or local/privileged mutation. |
| `evidence` | Information supporting a claim or verification. |
| `artifact` | A file, report, message, pull request, URL, or other deliverable. |
| `blocker` | A condition preventing progress. |
| `recovery` | An attempted or successful route around a blocker. |
| `milestone` | A human-relevant lifecycle boundary. |
| `learning` | A discovered invariant, correction, or reusable insight. |
| `play_candidate` | A proposed reusable procedure. |
| `play` | A verified released procedure. |

### Status vocabulary

```text
planned
active
waiting
blocked
satisfied
failed
skipped
superseded
verified
```

`verified` is never model-authored. It is derived from Play/Rote evidence and typed verification
receipts. A model or agent may propose `satisfied`, after which the projector validates it.

### Edge kinds

```text
decomposes_into
requires
selects
authorizes
executes
produces
verifies
blocked_by
recovers
derived_from
refines
crystallizes_into
```

### Evidence references

Each node can cite multiple evidence classes without duplicating payloads:

```json
{
  "play_events": ["<typed-event-id>"],
  "rote_commands": [7, 8, 9, 10],
  "rote_responses": ["@4", "@5", "@6"],
  "receipt_refs": ["sha256:<digest>"],
  "artifact_refs": ["sha256:<digest>"]
}
```

An operation has one primary semantic parent and may support additional evidence nodes. Operations
that are setup noise, duplicate inspection, or not yet classifiable remain hidden supporting
evidence. They are never discarded from Rote.

## Snapshot contract sketch

```json
{
  "schema": "play.journey-viewport/v1",
  "generation": 14,
  "projection_version": "rules-v1",
  "state": "active",
  "intent": {
    "label": "Retrieve rideshare receipts",
    "source": "play_capture"
  },
  "nodes": [
    {
      "id": "node_capability_gmail",
      "kind": "capability",
      "label": "Find the Gmail capability",
      "status": "verified",
      "confidence": "deterministic",
      "evidence": {
        "play_events": [],
        "rote_commands": [1, 2],
        "rote_responses": ["@1", "@2"],
        "receipt_refs": [],
        "artifact_refs": []
      },
      "telemetry": {
        "duration_ms": 812,
        "payload_tokens": 420,
        "tokens_saved": 0
      }
    }
  ],
  "edges": [
    {
      "source": "node_capability_gmail",
      "target": "node_authority_gmail",
      "kind": "requires"
    }
  ],
  "current_node": "node_retrieve_receipts",
  "presentation": {
    "has_material_change": true,
    "changed_node_ids": ["node_retrieve_receipts"],
    "complete": false,
    "total_nodes": 184,
    "total_edges": 312,
    "evidence_refs_omitted": 26
  },
  "source_cursor": {
    "play_events": 5,
    "rote_command_sequence": 18,
    "rote_response_id": 14
  },
  "updated_at": "2026-08-19T00:00:00Z"
}
```

The complete graph schema has no node, edge, evidence-reference, dependency, activity, or
changed-node array caps. The viewport schema uses bounded strings and arrays, rejects undeclared
fields, and caps only the foreground snapshot size. The complete Play semantic graph remains in
SQLite; the complete raw operational evidence remains in Rote. Neither is pruned by viewport
limits.

## Classification pipeline

### 1. Normalize Rote records

The ingester decodes the JSON command log into a stable Play-owned activity shape:

```text
sequence, response refs, command family, provider, adapter, operation,
process program, declared/policy effect, status, timing, dependency refs
```

This isolates the semantic classifier from Rote serialization details and gives schema drift one
fail-closed boundary.

### 2. Apply deterministic rules

Rules classify structural facts conservatively:

| Evidence | Classification |
|---|---|
| Catalog search, probe, tool listing, adapter inspection | `capability` |
| `adapter.auth.ensure`, token-health check, browser auth | `authority` |
| Adapter tool `readOnlyHint: true`, or HTTP `GET`/`HEAD`/`OPTIONS` | `effect` with `read` posture |
| Adapter tool `readOnlyHint: false`, or HTTP `POST`/`PUT`/`PATCH`/`DELETE` | `effect` with `write` posture |
| Process policy `risk_tags` containing both read and write scopes | `effect` with `mixed` posture |
| Process policy `risk_tags` containing a write or privileged scope | `effect` with `write` posture and bounded policy attributes |
| Browser observation primitive (`inventory`, `ledger`, `slice`, `lens`, `wait`) | supporting `evidence` with read posture |
| Browser navigation or page-lease mutation | external `effect`; navigation has read posture while an untyped lease mutation remains unknown |
| Browser policy gate/auth restore or capture failure | `authority` or `blocker`, respectively |
| Browser action without a typed effect receipt | unknown external effect |
| Query/extraction/transformation | supporting `evidence` or phase work |
| Assertion, comparison, smoke test | `evidence` with verification candidate |
| Produced content-addressed file or canonical URI | `artifact` |
| Failed operation | `blocker` |
| Equivalent successful operation after failure | `recovery` |

Every normalized activity carries a `play.journey-effect/v1` record with `posture`, `scopes`,
`source`, `confidence`, and `destructive`; typed sources may also retain bounded `risk_tags` and HTTP
`methods`. Unknown operations remain explicitly `unknown`. The classifier may not infer read-only
safety from a program or operation name such as `curl`, `gh`, `get_user`, or `delete_cache`.

The effect posture has a closed source precedence. Adapter calls use the exact nested operation to
look up Rote's installed `tools.json` contract, preferring MCP tool hints and falling back only to
the declared HTTP method. Process activity uses Rote's persisted process-policy `risk_tags`.
Browser activity uses the typed ledger primitive and the allowlisted action on tab-management
requests. Workspace query/display records use their Rote
command type. Missing or contradictory evidence fails closed to `unknown`; network-bearing process
records remain unknown unless Rote supplies a stronger typed contract.

Free-text arguments, inline source, shell bodies, search needles, operation verbs, arbitrary
request payloads, and response content never influence read/write posture. A command or adapter
operation containing
words such as `get`, `list`, `delete`, `publish`, or `approve` therefore cannot manufacture safety or
authority. Browser initialization is capability discovery; typed tab inventory and
ledger/slice/lens/wait records are observations;
unsafe or opaque browser actions remain unknown until a typed effect receipt exists.

Supporting `QueryRead`/`QueryExtract` activity attaches to the semantic node that owns its declared
`source_response`. It never attaches merely to the most recently projected node. This preserves the
causal evidence relationship when an agent reads an older response after newer work has occurred.
Classifier revisions increment `projection_version`; the background projector then rebuilds even
when the underlying Rote workspace fingerprint has not changed.

### Capability substrate is orthogonal to semantic kind

Every normalized activity also carries a `play.journey-capability/v1` descriptor. Semantic kind
answers **why the interaction exists** (`effect`, `evidence`, `authority`, and so on); the
capability descriptor answers **what execution system performed it**. Conflating these planes made
the viewer label cached queries as tools and shell wrappers as services.

| Rote substrate | Journey family | Persisted safe vocabulary | Viewer model |
|---|---|---|---|
| canonical `adapter/<id>` MCP `tools/call` and `DataQuery` | `adapter` / `api` | adapter ID and name, `probe`/`call` phase, wrapper mode, concrete operation names, manifest schema, spec type/version, transport, auth type, operation scope, fingerprint, status | API station with its typed service contract |
| `ProcessExec`, PTY, background and stream records | `proc` / `shell` | actual CLI/program and mode (`argv`, `pty`, `background`, lease lifecycle, stream) | local tool loadout |
| Playwright/browser stdio plus the browser ledger | `browser` / `browse` | page lease, ledger/snapshot, slice, evidence lens, action, wait and rebase primitives | navigation system rather than a generic adapter |
| cached query/display and workspace bookkeeping | `rote` / `workspace` | query, extract, display or workspace primitive | supporting memory, visually subordinate to capabilities |

The Rote browser repository calls the compact snapshot view a **slice**. “Lens” is Play's
user-facing name for a query/extraction focused through a browser response; it is assigned only by
the declared `source_response` edge. Adapter manifests are read once by the detached projector and
reduced to the allowlisted fields above. The viewer never reads Rote manifests, browser ledgers, or
command payloads while rendering.

Adapter ownership is parsed from Rote's wire contract, not guessed from UI text. The endpoint must
be canonical `adapter/<id>` (with the accepted optional leading slash), the request must carry the
MCP method `tools/call`, and generated envelopes are matched against the adapter-normalized
`<id>_probe`, `<id>_call`, `<id>_batch_call`, or `<id>_probe_call` grammar. Single-call operations
come from `params.arguments.tool_name`; batch operations come from every
`params.arguments.calls[].tool_name`. A generic HTTP request, a provider display label, and a
cached `QueryRead` cannot equip an adapter. Legacy projections that no longer retain this typed
wire evidence remain explicitly unclassified instead of receiving a guessed capability.

The capability rail consumes the same typed record rather than deriving access from its label. It
groups execution systems as adapter/API, process/shell, and browser/browse, then displays each
system's aggregate `READ`, `WRITE`, `READ + WRITE`, or `UNKNOWN EFFECT` posture and scopes. The
vantage frontage preserves every chronological interaction index and binds it to the corresponding
tower and evidence reference. The timeline is explanatory display geometry; canonical activity and
evidence remain in the full graph.

This enrichment occurs only in the detached projector. Adapter tool indexes are loaded at most once
per adapter per worker and are never read by the prompt hook or browser viewer, preserving the zero
foreground-work constraint.

### 3. Segment with DAG motifs

The segmenter groups normalized activities using, in order:

1. explicit Play/controller boundaries;
2. dependency connectivity;
3. repeated adapter and operation fan-out;
4. known motifs such as probe→call, auth→call, list→get-many→transform, and
   failure→configuration→successful-retry;
5. provider/tool-family changes;
6. bounded temporal gaps.

Dependency topology has priority over time. Query reads feeding a later operation attach as
supporting evidence rather than appearing as standalone phases.

### 4. Apply semantic hints

The agent performing the exploration may supply a typed phase hint at a genuine purpose change:

```json
{
  "schema": "play.journey-hint/v1",
  "kind": "phase",
  "label": "Retrieve matching receipts",
  "boundary": "complete",
  "evidence_refs": ["@7", "@8", "@9", "@10"]
}
```

Hints are carried in an existing Play handoff or appended through a small local helper; they do not
trigger another model inference. The projector validates every reference and treats the supplied
status as a proposal.

The first implementation must work without hints. Hints improve labels and grouping but are never
required for execution.

### 5. Optional asynchronous enrichment

Model-based naming or regrouping is explicitly outside the initial critical path. A later enricher
may receive only sanitized operation signatures, graph structure, user intent, and safe manifest
descriptions. It writes proposed annotations with provenance and confidence. It cannot change
effect, authority, success, or verification facts.

No model enrichment is enabled by default until its latency, cost, privacy, and stability are
measured against the historical capture corpus.

## Foreground rendering

The response-completion hook reads `snapshot.json` only when:

- a capture is active;
- the snapshot exists and validates;
- its generation is newer than the last presented generation;
- `has_material_change` is true;
- the existing presentation throttle permits a pulse.

It renders only the semantic delta:

```text
📍 Exploration progress

Retrieve rideshare receipts
✓ Gmail connected
● Retrieving matching receipt emails
○ Reconcile trips and totals

Recovered: the original Gmail credential lacked the required read scope.
```

Telemetry is secondary and compact. Raw `@N` rows and edges appear only in an explicit creator or
diagnostic view.

If the snapshot is absent, stale, malformed, locked, or too large, the hook remains silent. It never
falls back to synchronous Rote inspection.

## Performance budget

These are design acceptance targets, measured as incremental cost beyond the existing hook:

| Path | Target |
|---|---|
| Prompt-submit overhead | zero Journey work |
| Response-completion snapshot check, p50 | ≤ 2 ms |
| Response-completion snapshot check, p95 | ≤ 10 ms |
| Hard foreground Journey budget | 25 ms; abort and remain silent |
| Foreground subprocesses | zero |
| Foreground SQLite/Rote workspace reads | zero |
| Snapshot size | ≤ 128 KiB default; hard cap 512 KiB |
| Event append | constant-size, atomic, no writer wait |
| Active semantic refresh | normally ≤ 2 s behind persisted Rote state |
| Idle worker CPU | effectively zero between polls |
| Worker idle exit | configurable, default 10 minutes |
| Worker memory | bounded; target ≤ 40 MiB RSS |

The worker ingests only the Rote delta after its stored source cursor and transactionally updates
the complete graph. It may derive a bounded viewport from that graph, but never deletes canonical
history to make the viewport fit. A full rebuild is explicit, version-triggered, or crash
recovery—not the normal refresh path.

## Concurrency and consistency

### Single writer

The capture-scoped lease guarantees one projection writer. Lease metadata includes PID, process
start identity where available, classifier version, and heartbeat. Stale leases are recoverable.

### Atomic publication

The worker commits the complete semantic graph in one SQLite transaction, then writes a temporary
viewport, `fsync`s as appropriate, and atomically replaces `snapshot.json`. Foreground readers
never observe partial JSON and never open SQLite. A crash between graph commit and viewport replace
is repaired from SQLite without rereading Rote.

### At-least-once ingestion, idempotent projection

Workers may read the same Rote or Play event more than once. Stable source identities and cursors
make event application idempotent.

### Eventual during work, bounded at lifecycle boundaries

Live exploration is eventually consistent. At outcome verification or crystallization, Play may
request a final worker catch-up with a small deadline. Missing the deadline does not invalidate the
outcome: crystallization falls back to the authoritative Rote evidence and can rebuild or enrich
the Journey later.

The Journey must never become a new guard that blocks the existing verified trajectory.

## Crystallization mapping

The semantic graph becomes an intermediate representation, not an automatic release:

| Journey element | Candidate Play contract |
|---|---|
| `intent` | Play name and description input |
| Outcome-bearing `phase` nodes | Candidate steps |
| Rote dependency edges | Step inputs and DAG edges |
| Reusable `decision` nodes | Parameters or explicit branches |
| `capability` nodes | Adapter, CLI, browser, or process requirements |
| `authority` nodes | Authentication family, credential name, and scopes |
| `effect` nodes | Inspection disclosure and approval class |
| `evidence` nodes | Tests and verification contract |
| `artifact` nodes | Output and presentation contract |
| Recurrent `recovery` nodes | Fallback or troubleshooting guidance |
| `learning` nodes | Invariants and authoring guidance |

Promotion remains selective:

```text
successful outcome-bearing path  → main candidate DAG
required setup                    → requirements/authentication
varying decisions                 → parameters
useful repeatable recovery        → fallback or guidance
one-time debugging                → Journal only
abandoned route                   → provenance only
```

The crystallizer verifies proposed step membership against the Rote dependency graph. Semantic
grouping does not override data dependencies.

## Direct-mode boundary

`direct:` bypasses Play and Rote for the entire turn. A direct excursion may appear in the human
history only as an external, unverified detour recorded from Play's turn boundary:

```text
captured exploration → direct excursion → resumed exploration
```

It contributes no Rote response references and is ineligible for crystallization. If its result is
necessary to the reusable procedure, that result must be reproduced or verified in the captured
Rote workspace after exploration resumes.

## Privacy and security

The Journey store may contain safe intent and phase labels, operation signatures, provider and
adapter IDs, counts, status, duration, token totals, hashes, and opaque evidence references.

It must not contain:

- credentials, authorization codes, cookies, or token values;
- raw request or response bodies;
- email contents, document contents, or other adapter payloads;
- sensitive parameter values;
- shell stdout/stderr;
- absolute workspace paths in user-facing or exported snapshots;
- model chain of thought.

Labels produced from manifests or hints pass the existing inert-label sanitation and bounded-length
rules. The schema rejects undeclared fields. A redaction failure drops the annotation rather than
the source evidence.

## Failure behavior

| Failure | Required behavior |
|---|---|
| Worker fails to start | Exploration continues; hook remains silent; later hook may schedule restart. |
| Worker crashes | Lease expires; replacement rebuilds from last cursor or source. |
| Rote CLI read fails or times out | Back off; retain last valid snapshot; never retry in foreground. |
| Rote schema drifts | Mark projector degraded; preserve prior snapshot; require classifier update. |
| Play event spool malformed | Skip invalid event and record private diagnostic; do not alter machine state. |
| Snapshot malformed or oversized | Reader ignores it; writer rebuilds bounded snapshot. |
| Semantic hint references missing `@N` | Reject hint; keep operations unclassified/supporting. |
| Classifier changes grouping | Create a new projection generation/version; raw evidence remains unchanged. |
| Final catch-up misses deadline | Continue verification/crystallization from raw Rote evidence. |

## Observability

Worker health is owner-private and separate from the user Journey:

```text
generation
source cursor
last successful refresh
last refresh duration
Rote read durations
classification duration
snapshot write duration
backlog size
degraded reason
worker restarts
```

Diagnostics must be explicitly requested. Normal users see no worker narration.

## Public/internal interfaces

Initial internal commands:

```text
play-journey worker --capture <opaque-ref>
play-journey snapshot --capture <opaque-ref> --json
play-journey graph --capture <opaque-ref> --json
play-journey scene --capture <opaque-ref> --json
play-journey view --active
play-journey rebuild --capture <opaque-ref>
play-journey doctor --capture <opaque-ref> --json
```

Typed phase hints remain a later extension; the initial implementation is fully deterministic and
does not expose a hint command.

The capture reference remains owner-private and should normally be resolved from active Play state.
`snapshot`, `graph`, `scene`, and `doctor` are diagnostic reads. `view` starts a detached read-only
loopback renderer and returns immediately. `rebuild` replaces only the disposable semantic
projection.

Current user surface:

```text
$play journey live
```

Possible later inspection surfaces:

```text
$play journey
$play journey detailed
$play journey why <phase>
$play journey evidence <phase>
```

The detailed conversational inspection commands are not part of the first implementation.

## Rollout

### Phase 0 — corpus and schema

- Freeze `play.journey-graph/v1`, `play.journey-viewport/v1`, and their privacy contracts.
- Select representative historical captures: Gmail, Calendar, GitHub, PostHog, MCP/DCR, browser,
  local shell, failure/recovery, and direct detours.
- Manually label their desired semantic graphs as golden fixtures.
- Benchmark current foreground hook latency and Rote JSON read cost.

### Phase 1 — offline deterministic projector

- Ingest command/dependency/stats JSON from completed historical workspaces.
- Normalize activities and implement conservative structural rules.
- Collapse repeated calls, attach query reads, and recognize failure/recovery motifs.
- Compare output to golden fixtures; do not integrate hooks.

### Phase 2 — background worker and snapshot

- Add capture-scoped lease, change fingerprint, delta cursors, atomic event log, and bounded snapshot.
- Launch worker at captured exploration start.
- Add crash, duplicate-worker, stale-lease, schema-drift, and rebuild tests.
- Measure CPU, memory, refresh lag, and Rote contention.

### Phase 3 — snapshot-only pulses

- Change the exploration Stop hook from synchronous Rote analytics to snapshot-only reads.
- Render semantic deltas with existing interval/time throttles.
- Keep the existing raw pulse behind an explicit diagnostic flag during rollout.
- Prove the hard foreground latency budget under large workspaces and concurrent writes.

### Phase 4 — crystallization input

- Pass the verified semantic snapshot to `rote-flow-crystallization` alongside authoritative raw
  evidence.
- Use phase membership as an authoring proposal, never as a dependency override.
- Verify that setup probes and abandoned routes are excluded from main candidate steps.

### Phase 5 — live renderers and optional enrichment

- Implemented: derive complete, stable `play.journey-scene/v1` geometry from the canonical graph.
- Implemented: derive an evidence-linked `play.journey-story/v1` human landmark traversal without
  mutating or pruning the canonical graph.
- Implemented: serve the compiled React Three Fiber/Three.js viewer through a detached,
  token-protected `127.0.0.1` process; the installed viewer has no Node runtime dependency.
- Implemented: workspace selection, light/dark themes, live generation following, pan, zoom, fit,
  journey replay, telemetry, and evidence-reference inspection.
- Retained: `play.journey-scene/v1` as a deterministic diagnostic contract; it is no longer the
  primary presentation surface.
- Keep renderer and any later enrichment failures isolated from the capture worker and Play machine.

#### Reusable spatial grammar inside a vantage

The world model and the activity record use two nested scales. Semantic stages remain the macro
journey. Recorded interactions inside one stage use the renderer-independent
`play.temporal-corridor/v1` grammar:

- earlier work is left and later work is right on a compact frontage timeline;
- canonical command sequence is authoritative ordering;
- every `@N` index remains visible on the timeline, with its tower clustered immediately behind it
  and in front of the semantic landmark;
- horizontal distance is elapsed time on a bounded logarithmic scale, so a long wait is visible
  without pushing the rest of the journey off-screen;
- depth lanes are allocated only when typed timestamps and durations prove that intervals overlap;
  sequential work remains in one compact row;
- a temporal spine, explicit index ticks, and concurrency connectors explain the cluster;
- tower height remains latency/payload telemetry and never encodes time, importance, or quality;
- every projected point retains sequence, timestamp interval, delta, lane, and the original
  interaction reference.

The grammar returns plain geometry and contains no Three.js, Deck.gl, DOM, or terminal dependency.
The 3D world, atlas, static captures, and later terminal projections can therefore render the same
placement contract without recreating chronology heuristics. Missing timestamps degrade to stable
sequence spacing; they never manufacture parallelism.

## Test and benchmark plan

### Correctness

- Every evidence reference resolves to the bound capture workspace or a valid Play receipt.
- No operation is silently dropped; it is assigned, supporting, or unclassified.
- Canonical SQLite retains every semantic node, edge, activity, dependency, and evidence mapping;
  only the foreground viewport may summarize or omit entries.
- Model/agent annotations cannot set verified state.
- A failed operation followed by a successful retry produces blocker/recovery semantics.
- Direct-mode turns never become verified Journey evidence.
- Rebuilding with the same projector version is byte-equivalent except for declared volatile health
  metadata.
- Classifier upgrades produce a new projection version without changing Rote.

### Performance

- Prompt-submit path has no Journey filesystem or subprocess work.
- Stop hook reads a small valid snapshot within the p50/p95/hard budgets.
- Missing, malformed, locked, and oversized snapshots fail silent within the hard budget.
- A 10,000-command synthetic workspace is ingested incrementally without full rescans after the
  initial build.
- A burst of 100 Rote writes is coalesced and does not produce 100 CLI scans or snapshot writes.
- Worker polling while idle consumes negligible CPU.
- Concurrent Rote writes and worker reads do not increase foreground Rote operation latency beyond
  the agreed regression threshold.

### Privacy

- Secret-shaped environment fields, request bodies, response payloads, and absolute paths never
  enter events or snapshots.
- Fuzzed labels remain inert and bounded.
- Files and directories have owner-private permissions.
- Diagnostic output contains evidence identities and counts, not payloads.

### Interaction quality

- Users can state the current goal, active phase, blocker, required decision, and produced artifact
  from the semantic view.
- The default view remains useful with 100+ raw operations.
- Repeated fan-out appears as one meaningful node with an expandable count.
- No pulse appears solely because low-level command count advanced.

## Acceptance criteria for implementation

Implementation may replace the existing raw exploration pulse only when all of the following hold:

1. Historical golden captures produce useful semantic phase graphs without reading raw payloads.
2. Foreground hooks execute zero Rote subprocesses and satisfy the 25 ms hard budget.
3. Worker failure, crash, upgrade, and schema drift cannot affect exploration correctness.
4. The projection rebuilds deterministically from existing evidence.
5. Direct-mode and privacy boundaries have automated tests.
6. Crystallization treats the Journey as a proposal and validates against the Rote DAG.
7. The user-facing pulse shows semantic change rather than raw command telemetry.

## Decisions made

- The Journey Graph is owned by Play and stored outside the Rote workspace.
- Rote remains authoritative; no raw evidence is migrated or rewritten.
- The complete Play semantic graph is persisted without pruning in owner-private SQLite; bounded
  JSON is a presentation viewport, not the canonical graph.
- Construction is asynchronous and capture-scoped.
- Foreground hooks are snapshot-only and fail silent.
- The first implementation uses Rote's existing JSON inspection commands rather than direct SQLite
  access or text trace parsing.
- Deterministic classification ships before optional model enrichment.
- The graph is foundational for crystallization and later renderers, but neither depends on the
  other shipping simultaneously.

## Open questions

1. Should phase hints be appended through a dedicated helper or carried only in existing typed Play
   handoff receipts?
2. Which Rote response-envelope metadata is stable enough to expose status and duration without
   reading payloads?
3. Should a final Journey catch-up at `exploration_verify` wait up to 250 ms, 500 ms, or not wait at
   all?
4. What worker refresh lag is perceptibly “live” for a terminal renderer without causing needless
   Rote CLI reads?
5. Which recovery patterns deserve promotion into a reusable Play versus remaining birth
   provenance?
6. Should projection rule versions be bundled with Play releases so old Journeys can be rendered
   with their original semantics?
