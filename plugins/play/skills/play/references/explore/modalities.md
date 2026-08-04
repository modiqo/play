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

Record selected modalities, justification, owner, constraints, and expected evidence in the
handoff packet. A modality succeeds only when it returns the declared event and evidence payload.

## Preserve policy

Keep write approvals, authentication limits, redaction rules, and human gates visible. Prefer a
read-only probe before a write where the specialist contract supports one. Do not treat access to
a tool as authority to perform an effect.
