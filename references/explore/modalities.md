# Modalities

Treat CALL, SHELL, and DRIVE as the only exploration modalities. A route may use one or combine
them. Transformation is ordinary data movement inside a route, not a fourth modality.

## Select a route

In `auto` mode, choose the smallest route that can verify the requested outcome:

1. Prefer CALL when an installed, authorized adapter exposes the needed capability. Use it for
   stable typed operations, especially when the task spans many records or repeated calls.
2. Prefer SHELL for fast local work: files, commands, processes, logs, dependency checks, and CLIs.
3. Use DRIVE when no suitable API or CLI exists, or when the task depends on the user's active,
   authenticated browser session. Attach to the active tab instead of creating a disconnected
   session when session state matters.
4. Combine modalities only when a single modality cannot produce and verify the outcome.

In `manual` mode, use only the modalities the user named. Preserve explicit exclusions such as
“shell only” or “do not browse.” If the constrained route cannot work, emit
`modality_widening_required`; never widen silently.

## Route to an owner

- CALL routes to the applicable adapter skill and its workspace/runtime guidance.
- SHELL routes to `rote-shell`.
- DRIVE routes to `rote-browse` and attaches to the active session when required.
- Combined work routes through the specialist that can preserve a single evidence chain.

These mappings are closed. In particular, CALL never means “call an exposed MCP tool directly.”
Before execution, confirm that the exact mapped rote-* skill is exposed as callable in the current
harness. Installed files and lower-level tools are not substitutes. If the owner is unavailable,
block without executing the route.

Record selected modalities, justification, owner, constraints, and expected evidence in the
handoff packet. Invoke only that specialist, then validate its typed receipt against the packet. A
modality succeeds only when the receipt matches the run, state, action, owner, event, and evidence
payload.

CALL must pass through typed adapter discovery before its execution handoff. Search installed
adapters first. When none adequately covers the capability, always search the built-in Rote adapter
catalog. Present every catalog match, keeping REST/OpenAPI, GraphQL, and MCP entries distinct, and
let the user choose. Only a successful zero-result catalog search or explicit rejection of every
match permits a supplied specification or authoritative provider-document search.

Bind the discovery query, ordered searched sources, choices, selection, and evidence into the CALL
packet. Reuse the selected installed adapter when possible. Otherwise `rote-adapter-create`
determines the substrate as `openapi`, `graphql`, or `mcp` from the selected catalog entry or later
specification evidence and creates it through Rote.
Authentication required during creation is completed by `rote-adapter-create` with the normal
human gate. Recoverable authentication failure on an existing adapter follows the separate flow
below.
Provider specifications, endpoint metadata, and MCP server cards are discovery-only; the final
capability call still runs through `rote-using-adapters` and reports adapter/type/auth provenance.

When `rote-using-adapters` classifies a CALL authentication failure as recoverable, it returns the
typed adapter id, environment variable, opaque repair rung, distinguishing error, and evidence.
Play asks whether to repair, then delegates a separate packet only to `rote-adapter-config`. Play
does not interpret the rung or handle credentials. A validated successful repair produces a fresh
execution packet that preserves the original inputs and idempotency key; it does not itself satisfy
the requested outcome.

## DRIVE crystallization limit (current version)

Typed browser steps can express navigation, waits, clicks, typing, and the canonical extract
slices (`clickable|links|headings|forms|errors`) only. They cannot carry a raw page snapshot or
arbitrary DOM/table cell content, and front-end accessibility trees are volatile across sites and
releases. A browser outcome whose required facts are not representable as a canonical slice can
therefore crystallize only as a legacy stepless body, which `rote play run` rejects
(`play_run_eligible: false`) and which must not be published as a runnable Play without explicit
user approval of that limitation.

Warn the user before exploration begins — at the Explore offer, or at the DRIVE route milestone
when consent was already implied — whenever the route includes DRIVE and the outcome depends on
extracting page content beyond the canonical slices (a table, grid, or arbitrary text). Say, to
the effect: browser extractions like this cannot be crystallized into a `rote play run`-eligible
Play in this version; a successful result can be kept as a verified outcome or preserved as a
local legacy Flow replayed with `rote deno run`. At `save_offer`, repeat the limit so
Private/Public/Skip is decided with full knowledge, and treat `play_run_eligible: false` from any
push or release surface as a publication gate.

## Preserve policy


Keep write approvals, authentication limits, redaction rules, and human gates visible. Prefer a
read-only probe before a write where the specialist contract supports one. Do not treat access to
a tool as authority to perform an effect.

Probe annotations such as `readOnlyHint` and `destructiveHint` describe discovery metadata; they do
not grant, deny, or request effect approval. After a probe identifies a matching operation, let the
Rote specialist attempt it through the adapter. Only Rote's structured `confirmation_required`
response is a write-approval gate. Pass that exact guard to Play for approval and resume the same
workspace and call only with the returned confirmation token.
