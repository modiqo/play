# Play Search

Use the bundled `scripts/bin/play-search <query> --json` for outcome discovery and
`scripts/bin/play-search <query>` for a user-facing search request. The wrapper combines local
Plays, private Plays in every authorized organization, and public-hub Plays visible to the user
into one deterministic result set.

## Normalize before searching

1. Apply Unicode NFKD normalization and case folding.
2. Keep Unicode letters and numbers, discard combining marks, and replace punctuation, symbols,
   control characters, and separators with spaces.
3. Collapse whitespace and remove repeated tokens while preserving their first-seen order.
4. Refuse a query containing no searchable letters or numbers after normalization.

Build one additional bounded discovery query by removing request verbs, conversational filler,
month names, and standalone numbers. This keeps outcome identity (for example `rideshare receipts`)
while leaving dates and other values for Play parameters. Never pass the raw user description to an
underlying query parser.

## Search concurrently and completely

Start all read-only full and discovery-query searches concurrently:

- Local: `rote play search <normalized-query> --limit <expanded-limit> --json`
- Authorized registry: `rote registry play search <normalized-query> --limit <expanded-limit> --json`.
  Partition its complete authorized response into private organization and public-hub results.

Capture successful stderr so endpoint warnings do not contaminate structured output. If either
search fails or returns malformed JSON, return an incomplete search failure rather than silently
using one source.

## Canonicalize and deduplicate

- Use `owner/name` as the canonical identity whenever available.
- Collapse registry versions under one canonical identity and retain the highest semantic version.
- Collapse local aliases into a canonical identity only when name and normalized description map
  unambiguously to one locally identified or registry Play.
- Never merge matching names from different organizations without that evidence.
- Combine source ranks with reciprocal-rank fusion and sort deterministically. Rank adequate matches
  by execution scope first: local, then private organization, then public hub.

For registry-addressable results, emit:

- exact URI: `https://play.modiqo.ai/<owner>/<name>@<version>`;
- sources: `local`, `remote_private`, `remote_public`, or a combination;
- local availability and whether a pull/install is expected;
- next command: `rote play inspect <owner>/<name>@<version> --json`.

For a local-only Play, emit its `file://` URI and use its local path for inspection and execution.

## Present choices

Show the normalized query and that both sources completed. For each result show name, sources,
version, fused score, URI, local availability, and next inspection command. If a Play is available
only in an authorized organization, state that a local pull/install is expected before it can run.
For an outcome request, deterministically select the first adequate result by that priority. Inspect
it read-only. If inspection proves the exact Play is already local, continue immediately to
execution. If it requires a pull, install, replacement, or repair, elicit explicit consent before
the runtime performs that change. Search-only requests still present structured choices; a choice
authorizes inspection only.
