# Play Awareness Digest

Use this guidance for daily or weekly digests, new or revised Plays, top public Plays, and personal
impact summaries. Awareness is externally read-only and precedes Use; remembered mode may update
only its declared local SHA/checkpoint store. Do not merge it into execution.

## Collect

Use `scripts/bin/play-digest --remember --days <n> --json` for an explicit user request. Require
`play.digest/v1`, `complete: true`, an
explicit time window, authorized organization results, section-level capability status, and a
declared public ranking metric and scope.

Remembered mode stores only the authorized-scope contract, stable `awareness_sha`, and successful
UTC checkpoint in `~/.rote/play/digest-state.json` with user-only file permissions. The scope key
includes organization slugs, initial window length, and inspection limits. It stores no digest
cards, credentials, or registry payloads. `--state <path>` overrides the location for an authorized
host or isolated test.

The awareness SHA represents the current organization publication and inspected public-ranking
snapshot; it excludes the moving digest window. Compare it with the previous SHA:

- `initial`: present the complete first digest.
- `changed`: present the new/revised window and current public ranking.
- `unchanged`: emit `awareness_unchanged`, say only “Nothing changed since your last Play digest.”,
  and finish without the action selector.

Advance memory only after stdout has been flushed successfully. A failed collection never changes
the stored SHA or checkpoint. Different authorized organization sets or digest configurations use
different memory streams.

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

Use the `select_awareness_action` elicitation. Selecting a card carries only its exact displayed
reference and parameters into read-only inspection. After the dependencies, local convergence,
operations, and effects are disclosed, `approve_play_run` is the sole execution gate. Selecting
Describe a need enters normal Play search. Selecting Create a Play enters creator discovery.

The skill cannot invent a scheduler. Without `--remember`, `$play digest` emits a
`play.digest-checkpoint/v1` `next_checkpoint` but does not write it; an authorized host may persist
that object and pass it back with `--checkpoint <path>`. `--since <timestamp>` is the stateless
equivalent. With `--remember`, only the declared on-demand state file advances after successful
presentation.

On-demand remembered digests are the default habit loop and require no scheduler. For an explicitly
requested automatic delivery integration, read
[../integration/scheduling.md](../integration/scheduling.md) and keep scheduler state host-owned.
