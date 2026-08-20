# Play controller contracts

This directory is the executable documentation for Play's deterministic controller.

| File | Authority |
|---|---|
| [`machine.yaml`](machine.yaml) | States, owners, checkpoints, transitions, guards, and mutations. |
| [`actions.yaml`](actions.yaml) | Deterministic/model/specialist actions and their closed event contracts. |
| [`prompts.yaml`](prompts.yaml) | Human questions, choices, and typed payload requirements. |
| [`context.schema.json`](context.schema.json) | Complete `play.context/v1` state carried by a run. |
| [`handoff.schema.json`](handoff.schema.json) | Specialist and saved-Play handoff packets and receipts. |
| [`machine.schema.json`](machine.schema.json) | Declarative-machine syntax. |
| [`command-log.md`](command-log.md) | Transition-derived recall journal and pre-machine command routing. |
| [`command-log.schema.json`](command-log.schema.json) | Durable `play.recall-journal/v1` storage contract. |
| [`../explore/journey-graph.schema.json`](../explore/journey-graph.schema.json) | Complete, unbounded `play.journey-graph/v1` semantic projection. |
| [`../explore/journey-viewport.schema.json`](../explore/journey-viewport.schema.json) | Bounded `play.journey-viewport/v1` projection over the complete semantic graph. |
| [`../explore/journey-scene.schema.json`](../explore/journey-scene.schema.json) | Complete deterministic `play.journey-scene/v1` isometric geometry. |
| [`../explore/journey-story.schema.json`](../explore/journey-story.schema.json) | Human-readable, evidence-linked `play.journey-story/v1` projection consumed by the live viewer. |

`scripts/bin/validate-machine` validates the bundle before packaging. `play-machine describe
--json` reports the compiled bundle SHA and state counts. `scripts/bin/package-plugin --check`
ensures every controller contract shipped in the plugin is byte-for-byte current.

The command log and Journey projector are observers, not additional state machines. They consume successful transitions
after context validation and cannot select a target, mutate controller context, authorize an
effect, or prevent a Play from completing. Presentation also stays outside the transition loop:
captured exploration pulses are claimed from an asynchronously built snapshot by the Stop hook,
while the daily recall journal is shown only when the user asks for it. The foreground pulse path
never invokes Rote or reads its workspace.

An approved empty-search exploration is not a terminal standby. `record_standby` creates the
capture and workspace, then `capture_is_active` routes through the visible `exploration_begin`
phase to `exploration_execute`. That delegated state invokes the `rote` entrypoint with the
unchanged outcome and completed no-match evidence.
Rote owns all nested routing: `rote-task-routing` runs explore/inventory/catalog gates,
`rote-adapter-create` adapts an accepted API, `rote-shell` validates and records an accepted CLI,
and `rote-workspace` executes adapter work. Play accepts only a complete result plus a verified,
capture-bound workspace trajectory before entering verification and save judgment.
The exploration specialist never authors the trajectory receipt. On
`exploration_outcome_ready`, the runtime resolves the continuation's owner-private capture, runs the
Rote trajectory validator, and atomically binds `capture.status=verified`, the validator's
`sha256:…` trajectory reference, and the identical `evidence.verification`. Validation failure is
reported before transition, leaving the continuation active rather than falling through to a
generic terminal blocker.

Every accepted event projection includes both a prebound `event_template` and a self-contained
`payload_schema` with exact types, enums, and object shapes. Harnesses and specialists must fill
the template according to that schema instead of guessing metadata values.

Captured exploration distinguishes prerequisites from outcomes. Adapter setup, authentication,
token verification, capability probes, and smoke tests return `exploration_prerequisite_ready`
when they must cross a boundary; the machine then resumes the original exploration without
entering verification or save judgment. Only useful outcome-bearing work may return
`exploration_outcome_ready`.

Exploration intent is typed. A setup-led request such as `connect to PostHog` reaches
`exploration_goal_offer` after the connection is checked, while a goal-bound request such as
`connect to PostHog and retrieve DAU` resumes the declared DAU goal immediately. A useful
same-task refinement at `save_judge` returns to `exploration_execute` with the same capture and
workspace rather than ending the trajectory and starting another search.

An explicit publication request for an already released local Play enters
`local_release_inspect`. The read-only flow-authoring handoff must recover the exact unpublished
release and its originating verified workspace before the normal birth → registry publication →
binding → indexing → inspection path can continue. It never enters saved-Play search or new
exploration.

The exploration-only journey surface deterministically presents start, prerequisite-ready,
route-recovery, verified-completion, and one-off-completion phases. Tool discovery stays inside the
Rote specialist, which must present alternatives, retain an “another tool” choice, verify the
selected route, and wait before execution. A `direct:` turn leaves the Play continuation and Rote
workspace paused; it is not captured evidence and `continue exploration` resumes only after changed
external state is revalidated.

During an active capture, `play-journey` independently projects Rote's operational DAG into the
closed semantic vocabulary defined by `play.journey-graph/v1`. The foreground reads only
`play.journey-viewport/v1`. The worker reads
`workspace stats`, `workspace inspect log`, and `workspace inspect deps` as JSON only after a
constant-time workspace fingerprint changes. It stores no payload bodies or sensitive arguments.
The complete semantic graph is retained without pruning in owner-private SQLite; only the
foreground JSON viewport is bounded. Both are disposable and rebuildable, and neither is a
verification or crystallization guard; Rote remains the evidence authority.

`play-journey view --active` is the read-only live renderer. It resolves the active capture without
printing its reference, serves compiled WebGL assets only on `127.0.0.1` behind a random
owner-private token, replaces every older Journey HTTP server with one singleton on port `52050`
by default, and follows new generations without entering the Play machine or running
effect-bearing Rote work. Its `play.journey-story/v1` input is a deterministic human projection:
stable graph order fixes traversal, semantic kind fixes the teaching stage, and every landmark
retains opaque canonical evidence references. At the live head a new generation advances to the
newest call site; an inspected or frozen vantage remains pinned by semantic site identity rather
than drifting as a normalized percentage. Semantic zoom separates the human Journey, one
phase's recorded interactions, and a lazily loaded redacted exchange. The playback control enacts
the same deterministic traversal for static and live captures; it does not execute Rote or mutate
the capture. The complete graph—not the visual story or exchange display—is the audit authority.

Its owner-private workspace index lists every recorded capture using hashed Journey IDs, never raw
capture handles or filesystem paths. **Active** describes capture lifecycle and **Viewing** describes
selection; the UI never conflates either with a projector process. Selecting a graph-ready entry
changes only the story and event-stream read target. Selecting a pre-projector entry schedules its
isolated read-only projector and switches after the first derived graph is available; it never alters
the underlying Rote workspace.
