# Play Search

Use the bundled `scripts/bin/play-search <query> --json` for outcome discovery and
`scripts/bin/play-search <query>` for a user-facing search request. The wrapper combines the local
and authorized registry Play search surfaces into one deterministic result set.

## Normalize before searching

1. Apply Unicode NFKD normalization and case folding.
2. Keep Unicode letters and numbers, discard combining marks, and replace punctuation, symbols,
   control characters, and separators with spaces.
3. Collapse whitespace and remove repeated tokens while preserving their first-seen order.
4. Refuse a query containing no searchable letters or numbers after normalization.

Pass the normalized string as one argument to both underlying commands. Never pass the raw user
description to either query parser.

## Search concurrently and completely

Start these read-only searches concurrently:

- Local: `rote play search <normalized-query> --limit <expanded-limit> --json`
- Authorized registry: `rote registry play search <normalized-query> --limit <expanded-limit> --json`

Capture successful stderr so endpoint warnings do not contaminate structured output. If either
search fails or returns malformed JSON, return an incomplete search failure rather than silently
using one source.

## Canonicalize and deduplicate

- Use `owner/name` as the canonical identity whenever available.
- Collapse registry versions under one canonical identity and retain the highest semantic version.
- Collapse local aliases into a canonical identity only when name and normalized description map
  unambiguously to one locally identified or registry Play.
- Never merge matching names from different organizations without that evidence.
- Combine source ranks with reciprocal-rank fusion and sort deterministically.

For registry-addressable results, emit:

- exact URI: `https://play.modiqo.ai/<owner>/<name>@<version>`;
- sources: `local`, `registry`, or both;
- local availability and whether a pull/install is expected;
- next command: `rote play inspect <owner>/<name>@<version> --json`.

For a local-only Play, emit its `file://` URI and a `rote play run <path>` hint. Keep it out of
registry-addressable choices until publication provides a canonical reference.

## Present choices

Show the normalized query and that both sources completed. For each result show name, sources,
version, fused score, URI, local availability, and next inspection command. If a Play is available
only in an authorized organization, state that a local pull/install is expected before it can run.
When the user is choosing a match, use the harness's structured single-select elicitation and the
canonical exact reference as the choice value. A selection authorizes read-only inspection only.
After inspection, disclose purpose, parameters, dependencies, credentials, local setup, declared
operations, declared writes, and any unknown effect semantics. Only `approve_play_run` authorizes
the exact inspected version and displayed parameters for `rote play run ... --yes`.
