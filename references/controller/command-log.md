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

Captured exploration uses the active Rote workspace as its source of truth. The Stop hook first
checks whether an active capture has crossed both the configured step interval and time throttle.
When due, it reads `rote workspace stats --json` and `rote trace --deps`, claims one cursor, and
shows a compact progress pulse. It does not write those workspace commands into the recall command
log. Normal requests and recalled saved-Play runs never display workspace statistics.

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
