# Play Awareness Digest

Use this guidance for daily or weekly digests, new or revised Plays, top public Plays, and personal
impact summaries. Awareness is read-only and precedes Use; do not merge it into execution.

## Collect

Use `scripts/bin/play-digest --days <n> --json`. Require `play.digest/v1`, `complete: true`, an
explicit time window, authorized organization results, section-level capability status, and a
declared public ranking metric and scope.

Registry subprocesses are bounded by `PLAY_COMMAND_TIMEOUT_SECONDS` (30 seconds by default). A
required organization discovery timeout fails closed instead of freezing the harness. A host that
already knows the authorized scope may repeat `--org <slug>` to bypass discovery; this is a scope
assertion from the host, not permission to read an unauthorized organization.

Public inspection is also bounded (`--inspection-budget 8` by default). Candidates are selected
most-recently-updated first, then ranked by inspected lifetime downloads. When candidates are
omitted or an inspection fails, label the result as an inspected sample and return candidate,
inspected, and omitted counts; never call it exhaustive.

New and revised cards use a separate update inspection budget (four by default). Successful
inspection pins the card to `owner/name@version` and displays exact defaults. A card omitted from
or failed by inspection remains visible for awareness but is not an exact Use choice until a later
inspect succeeds.

- New means first publication occurred inside the window.
- Revised means a newer released version occurred inside the window. Require
  `latest_version_created_at`; `updated_at` alone may be a metadata edit and is not sufficient.
- Do not treat a visibility-only metadata edit as a revision.
- Include private Plays only from organizations authorized for the current identity.
- Enrich authorized public candidates with `rote play inspect <reference> --json`; use its exact
  owner, version, visibility, parameters, run eligibility, download count, and install count.
- Describe public results as trending only when the metric is windowed usage. Lifetime totals must
  be labeled most downloaded and must name their coverage scope.
- The current registry has no canonical global public enumeration. Label the default ranking
  `authorized_organizations` and report global public ranking as unavailable. Never imply that a
  relevance search or community list is an exhaustive global ranking.
- Report unavailable personal metrics as unavailable, never as zero.

## Present

Show compact New, Revised, Public, and Your impact sections. Each actionable card must carry the
canonical reference, owner, visibility, version when known, and displayed parameters.

Use the `select_awareness_action` elicitation. Selecting Run authorizes only the exact displayed
reference and parameters. Selecting Describe a need enters normal Play search. Selecting Create a
Play enters creator discovery.

The skill cannot invent a scheduler or persist a daily delivery cursor. `$play digest` emits a
`play.digest-checkpoint/v1` `next_checkpoint`; an authorized host may persist that object and pass
it back with `--checkpoint <path>`. `--since <timestamp>` is the stateless equivalent. The digest
command reads checkpoint state but never advances a file itself. Automatic delivery still needs an
authorized host hook or scheduler; `$play digest` remains the safe explicit entrypoint.
