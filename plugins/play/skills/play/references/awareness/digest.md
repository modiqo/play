# Play Awareness Digest

Use this guidance for “whats new” or “what's new”, daily or weekly Play inboxes, new or revised Plays, top public
Plays, and personal impact summaries. Awareness is externally read-only and precedes Use;
remembered mode may update only its declared local SHA/checkpoint store. Do not merge it into
execution. Treat `$play digest` as a compact alias, not the primary natural-language framing.

## Collect

Use `scripts/bin/play-digest --remember --days <n> --json` for an explicit user request. Require
`play.digest/v1`, `complete: true`, an
explicit time window, authorized organization results, section-level capability status, and a
declared public ranking metric and scope.

The digest and any inferred awareness invocation must reuse
`play.public_trends.fetch_authorized_public_stats`; integrations that already have exact public
references may call `scripts/bin/play-public-trends --play <owner/name[@version]> --json` directly.
Do not create a second stats-fetching path.

Remembered mode stores only the authorized-scope contract, stable `awareness_sha`, and successful
UTC checkpoint in `~/.rote/play/digest-state.json` with user-only file permissions. The scope key
includes organization slugs, initial window length, and inspection limits. It stores no digest
cards, credentials, or registry payloads. `--state <path>` overrides the location for an authorized
host or isolated test.

The awareness SHA represents the current organization publication and inspected public-ranking
snapshot; it excludes the moving digest window. Compare it with the previous SHA:

- `initial`: present the complete first digest.
- `changed`: present the new/revised window and current public ranking.
- `unchanged`: emit `awareness_unchanged`, say that nothing changed, and still present the current
  catalog summary and domain selector. “What’s new” is also the discovery entrance, so an unchanged
  acknowledgment must not become a dead end.

Advance memory only after stdout has been flushed successfully. A failed collection never changes
the stored SHA or checkpoint. Different authorized organization sets or digest configurations use
different memory streams.

Registry subprocesses are bounded by `PLAY_COMMAND_TIMEOUT_SECONDS` (30 seconds by default). A
required organization discovery timeout fails closed instead of freezing the harness. A host that
already knows the authorized scope may repeat `--org <slug>` to bypass discovery; this is a scope
assertion from the host, not permission to read an unauthorized organization.

Public statistics reads are bounded (`--inspection-budget 100` by default). Enumerate authorized
public candidates, then fetch their exact public `https://play.modiqo.ai/<owner>/<play>.json` cards
in parallel with no redirects, cookies, or credentials. Validate card identity and public
visibility before accepting `stats.downloads` and `stats.installs`. Group results by the card's
declared owner kind (`org`, `user`, or `unknown`), rank the successfully read candidates by lifetime
downloads, and show at most 10 by default. Record worker count, per-card latency, and total fetch
latency. When candidates are omitted or a read fails, label the result as an inspected sample and
return candidate, fetched, and omitted counts; never call it exhaustive.

New and revised cards use a separate registry metadata budget (100 by default) to retrieve released
version, lifetime totals, and `version.metadata.provenance.author`. Treat that author as publication
display metadata, not proof that it maps to the current signed-in identity. A second, separate update
inspection budget (four by default) pins successful cards to `owner/name@version` and displays exact
defaults. A card omitted from or failed by Play inspection remains visible for awareness but is not
an exact Use choice until a later inspect succeeds.

- New means first publication occurred inside the window.
- Revised means a newer released version occurred inside the window. Require
  `latest_version_created_at`; `updated_at` alone may be a metadata edit and is not sufficient.
- Do not treat a visibility-only metadata edit as a revision.
- Include private Plays only from organizations authorized for the current identity.
- Enrich new and revised cards with `rote registry play info <reference> --json` for released
  version and author provenance. Read public download and install counters only from the public Play
  card. Neither awareness read implies local installation or run eligibility; inspect a selected
  card before Use.
- Describe public results as trending only when the metric is windowed usage. Lifetime totals must
  be labeled most downloaded and must name their coverage scope.
- Registry Play list/info currently expose no run count. Report run metrics as unavailable and use
  lifetime downloads for ranking until a canonical run metric exists.
- The current registry has no canonical global public enumeration. Label the default ranking
  `authorized_organizations` and report global public ranking as unavailable. Never imply that a
  relevance search or community list is an exhaustive global ranking.
- Report unavailable personal metrics as unavailable, never as zero.

## Present

Present `# What’s new in Plays` progressively:

1. On an `initial` remembered view, put “Nice—you’ve taken the first step” before any heading or
   catalog data.
2. Show the number of inspected runnable public Plays and the number of organizations/domains that
   own them. Derive both from the current cards. Never hard-code a marketing total.
3. List organization/domain display names with their Play counts, but do not dump individual cards.
4. Recommend Hello and explain that inspection is an X-ray of the exact method and declared effects.
5. Use `select_awareness_domain` to ask for a domain. After selection, populate only that domain’s
   five most recently published or released Plays in `awareness.play_choices`, then use
   `select_awareness_play`. Keep the organization count as the complete eligible total rather than
   the shortlist length.

A cached digest is discovery-compatible only when its organization/domain projection is present
and its organization counts reconcile exactly to the runnable public Play total. Refresh a fresh
legacy cache that lacks this projection instead of rendering a misleading zero-organization count.

Complete inspection coverage supports an exact scoped count. Partial coverage must say “at least”
and disclose that the scope is the user’s authorized organizations, not the global registry.

Selecting a Play carries only its exact displayed reference and parameters into read-only
inspection. After dependencies, local convergence, operations, and effects are disclosed,
`approve_play_run` is the sole execution gate. Hello uses the same path. Selecting Find by outcome
enters normal Play search; selecting Create your own enters creator discovery, where capture must be
classified before exploratory work begins.

The skill cannot invent a scheduler. Without `--remember`, `$play whats new` (or `$play digest`)
emits a
`play.digest-checkpoint/v1` `next_checkpoint` but does not write it; an authorized host may persist
that object and pass it back with `--checkpoint <path>`. `--since <timestamp>` is the stateless
equivalent. With `--remember`, only the declared on-demand state file advances after successful
presentation.

On-demand remembered digests are the default habit loop and require no scheduler. For an explicitly
requested automatic delivery integration, read
[../integration/scheduling.md](../integration/scheduling.md) and keep scheduler state host-owned.
