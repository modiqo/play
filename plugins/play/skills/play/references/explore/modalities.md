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

CALL must converge on a Rote adapter before it can yield an outcome. Reuse a matching installed
adapter when possible. Otherwise `rote-adapter-create` determines the substrate as `openapi`,
`graphql`, or `mcp` from the strongest available evidence and creates it through Rote. Missing or
stale authentication is completed by `rote-adapter-create` or `rote-adapter-config` with the normal
human gate. Provider specifications, endpoint metadata, and MCP server cards are discovery-only; the
final capability call still runs through `rote-using-adapters` and reports adapter/type/auth
provenance.

## Preserve policy

Keep write approvals, authentication limits, redaction rules, and human gates visible. Prefer a
read-only probe before a write where the specialist contract supports one. Do not treat access to
a tool as authority to perform an effect.

Probe annotations such as `readOnlyHint` and `destructiveHint` describe discovery metadata; they do
not grant, deny, or request effect approval. After a probe identifies a matching operation, let the
Rote specialist attempt it through the adapter. Only Rote's structured `confirmation_required`
response is a write-approval gate. Pass that exact guard to Play for approval and resume the same
workspace and call only with the returned confirmation token.
