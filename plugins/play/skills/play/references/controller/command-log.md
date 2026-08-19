# Deterministic Play command log

Play keeps an owner-private, append-only-in-meaning command log for recalled saved Plays. The log
is a projection of successful typed controller transitions—not a transcript assembled by the
model. It answers: which saved Play matched, which one the user selected and approved, whether its
run started, and whether it completed or blocked.

The canonical storage contract is
[`command-log.schema.json`](command-log.schema.json) (`play.recall-journal/v1`). The default path is
`~/.rote-play/recall-journal.json`. The user-facing daily projection is:

```text
$play journal
$play journal yesterday
$play journal 2026-08-17
```

Those commands take the pre-machine local path. They run `scripts/bin/play-journal show --day
<day>`, read no registry or adapter, create no continuation, and run no preflight.

## Transition mapping

Only the transitions below may append recall events. An event ID is `<run_id>:<kind>`, so observing
the same transition twice is idempotent.

| Machine transition | Command-log event | Meaning |
|---|---|---|
| `qualify --exact_play_request--> use_inspect` | `selected` | The user named a saved Play directly. |
| `classify --full_match--> use_inspect` | `matched` | Search produced one adequate saved Play. |
| `search_offer --search_play_selected--> use_inspect` | `matched`, `selected` | Search surfaced a Play and the user chose it for inspection. |
| `use_offer --play_run_approved--> use_prepare` | `approved` | The user approved the disclosed remote pull/run. |
| `use_prepare --play_run_handoff_ready--> use_run` | `run_started` | The exact reference and parameters were bound for execution. |
| `use_receipt --receipt_ready--> receipt` | `completed` | Output verification completed and the receipt became terminal. |
| `use_receipt --receipt_ready--> onboarding_result_offer` | `completed` | The onboarding starter completed before its result-confirmation prompt. |
| `use_prepare|use_run|use_authentication_offer|use_authentication_execute|use_verify|use_receipt --> blocked|standby_exit` | `blocked` | The approved recalled-Play trajectory failed closed, including authentication recovery. |

Search-result presentation alone is not a selection and does not create one event per candidate.
Awareness browsing, ordinary direct-mode work, routing management, cheat-sheet reads, and captured
exploration do not enter this log.

## Privacy and retention

Each event contains only its schema, deterministic event ID, event kind, run ID, canonical Play
reference, timestamp, and local day. It never contains prompt text, parameter values, command
stdout/stderr, response payloads, credentials, token values, continuation IDs, or workspace paths.

The default retention window is 30 local days with a hard maximum of 1,024 events. Both are
converged from owner-private journal settings at install. Logging is observational: a malformed or
unwritable journal cannot interrupt the Play transition that produced it.

## Exploration is a separate journal

Captured exploration uses the active Rote workspace as its source of truth, with a disposable Play
Journey projection for human meaning. Capture creation starts one detached, low-priority
`play-journey` worker. The worker fingerprints the workspace in constant time, reads only Rote's
supported JSON surfaces when evidence changes, and groups operational `@N` activity into semantic
nodes such as capability, authority, effect, blocker, recovery, evidence, milestone, and Play
candidate.

The Stop hook never runs Rote, parses a trace, opens the workspace database, classifies activity,
or waits for the worker. It reads one bounded `play.journey-viewport/v1` snapshot and claims a material
generation exactly once. A missing, stale, malformed, slow, or oversized snapshot is silent. The
Rote workspace remains authoritative and the projection can be deleted and rebuilt without losing
evidence.

Journey state is owner-private under `~/.rote-play/journeys/`. `journey.sqlite3` retains the complete
semantic graph and its Rote evidence mappings without node, edge, activity, or evidence-reference
pruning. `snapshot.json` is only a bounded foreground viewport and declares whether it is complete,
the full node/edge counts, and how many evidence references are omitted from that viewport. It
contains safe intent and phase labels, operation/provider identities, status, counts, timing, token
totals, and opaque evidence references. It never contains raw request or response bodies, shell
output, credentials, sensitive parameter values, continuation IDs, or workspace paths. It does not
enter the recalled-Play command log. Normal requests and recalled saved-Play runs never display
exploration progress.

### Journey transition observations

The worker joins Rote evidence with this closed set of successful controller events. Observation is
best-effort and cannot mutate context, select a transition, authorize an effect, or block the run.

| Controller event | Journey meaning |
|---|---|
| `exploration_started` | Captured exploration began. |
| `exploration_prerequisite_ready` / `exploration_prerequisite_presented` | A connection or setup prerequisite became ready. |
| `exploration_goal_supplied` / `exploration_refinement_requested` | The user selected or refined the useful outcome. |
| `exploration_route_exhausted` | The selected route blocked. |
| `exploration_retry_selected` | The user chose another exploration route. |
| `outcome_verified` / `exploration_completion_presented` | The requested result was verified and presented. |
| `worth_saving` / `candidate_ready` | The verified path became a reusable Play candidate. |
| `not_worth_saving` / `exploration_stopped` | Exploration ended without creating a Play. |
| `birth_captured` / `birth_bound` | A released or published Play was bound to its provenance. |

### Journey diagnostic commands

These commands inspect or rebuild only the disposable semantic projection. They do not execute the
captured workflow:

| Command | Deterministic action |
|---|---|
| `play-journey snapshot --capture <opaque-ref> [--json]` | Read the latest valid semantic snapshot. |
| `play-journey graph --capture <opaque-ref> --json` | Read the complete persisted semantic graph and evidence mappings. |
| `play-journey story --capture <opaque-ref> --json` | Derive the deterministic human landmark sequence used by the live viewer without dropping canonical evidence references. |
| `play-journey scene --capture <opaque-ref> --json` | Derive the complete deterministic `play.journey-scene/v1` isometric geometry. |
| `play-journey view --active` | Start a missed projector if necessary, then open the token-protected WebGL Journey world; distinguish active captures from the workspace being viewed. |
| `play-journey doctor --capture <opaque-ref> --json` | Report bounded snapshot and worker health metadata. |
| `play-journey refresh --capture <opaque-ref> [--json]` | Run one incremental background-style refresh. |
| `play-journey rebuild --capture <opaque-ref> [--json]` | Rebuild the disposable projection from authoritative evidence. |
| `play-journey worker --capture <opaque-ref> [--once]` | Run the capture-scoped projector; duplicate workers exit on the lease. |

Install defaults live in `~/.rote-play/journal-settings.json`:

```json
{
  "schema": "play.journal-settings/v1",
  "enabled": true,
  "exploration": {
    "enabled": true,
    "interval_steps": 5,
    "min_interval_seconds": 120
  },
  "recall": {
    "enabled": true,
    "retention_days": 30
  }
}
```

Reinstallation fills missing settings but preserves an explicit opt-out.

## Deterministic command routing

The following surfaces deliberately execute before the main machine:

| User surface | Deterministic action |
|---|---|
| `play cheat-sheet` | Render the bundled cheat sheet. |
| `$play journal [day]` | Render the owner-private daily recall projection. |
| `$play what's new` | Render the cached digest and perform only its bounded refresh policy. |
| `direct: <request>` / `without play: <request>` | Stamp the entire turn as a Play-and-Rote bypass. |
| Play routing management | Execute `play-routing` against the explicit project or user scope. |

All saved-Play search, inspection, approval, authentication recovery, execution, verification,
capture settlement, creation, sharing, and publication trajectories remain owned by
[`machine.yaml`](machine.yaml).

## Bootstrap recovery command log

Install backup and restore are deterministic bootstrap transactions, not recalled-Play events, so
they never append to `play.recall-journal/v1`. Their complete command surface is recorded here:

| Command | Deterministic action |
|---|---|
| `play-bootstrap backup list [--json]` | List valid recovery manifests newest-first. |
| `play-bootstrap backup show <run-id> [--json]` | Inspect one immutable recovery manifest. |
| `play-bootstrap restore --dossier <install-report.json> --plan [--json]` | Validate the dossier and manifest hash, then show the exact restore plan without changing state. |
| `play-bootstrap restore --dossier <install-report.json> [--yes] [--json]` | Back up current Play state, restore the dossier's snapshot, verify it, and write a restore dossier. |
| `play-bootstrap restore --backup <run-id> --plan [--json]` | Build the same read-only plan directly from a retained backup ID. |
| `play-bootstrap restore --backup <run-id> [--yes] [--json]` | Apply a retained backup directly, with the same safety snapshot and verification. |

Every approved install creates its recovery manifest before plugin, portable-state, or hook
convergence. If the manifest contains prior Play state, the install result prints its dossier-driven
restore command. Only a completed, verified install or restore may prune recovery points; the newest
10 valid snapshots are retained. Shared harness files are merged by Play ownership during restore,
while Play-only files, directories, and launchers are restored exactly.

## Exploration and publication transition notes

These lifecycle transitions are deliberately outside the recall command log, but remain fully
typed in the machine:

| Transition | Meaning |
|---|---|
| `exploration_prerequisite_present --exploration_prerequisite_presented--> exploration_goal_offer` | A connection-only request is ready for its first useful outcome. |
| `exploration_prerequisite_present --exploration_prerequisite_presented--> exploration_execute` | Setup completed and the original request already contains a useful goal. |
| `save_judge --exploration_refinement_requested--> exploration_execute` | A same-task refinement continues in the same capture workspace. |
| `qualify --play_publication_request--> local_release_inspect` | An explicit existing-local-Play publication request bypasses search and creation. |
| `local_release_inspect --local_release_ready--> birth_capture` | The exact unpublished release and originating verified workspace were recovered. |
