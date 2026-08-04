# Play Search

Use the bundled `scripts/play-search <query> --json` for outcome discovery and
`scripts/play-search <query>` for a user-facing search request. `rote play` currently exposes no
search command, so the wrapper narrowly fills that capability gap.

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

- Local: `rote flow search <normalized-query> --limit <expanded-limit> --json`
- Authorized registry: `rote registry flow search <normalized-query> --limit <expanded-limit> --json`

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
- next command: `rote play run <owner>/<name>@<version>`.

For a local-only Flow, emit its `file://` URI and label its `rote flow run` hint as a capability gap.
Do not pretend a local path is accepted by `rote play run`.

## Present choices

Show the normalized query and that both sources completed. For each result show name, sources,
version, fused score, URI, and next command. When the user is choosing a match, use the harness's
structured single-select elicitation; use the canonical reference as the choice value. A selection
authorizes that exact reference and displayed parameters for `rote play run ... --yes`.
