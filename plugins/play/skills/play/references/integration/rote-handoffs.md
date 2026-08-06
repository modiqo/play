# Rote Handoffs

Play owns the user-facing lifecycle. Existing `rote-*` skills own domain execution. Hand off to the
narrowest applicable specialist after Play has selected a state and route.

Every installed Rote specialist must remain model/harness-invocable. A skill that can be invoked
only by an explicit user command cannot satisfy an internal handoff, even when its `SKILL.md` is
installed and readable. Keep Play as the preferred controller through routing instructions, not by
hiding the execution owners it must call.

## Packet

Provide a typed packet with:

```yaml
schema: play.handoff/v1
run_id: <play run id>
state: <current machine state>
action: <declared action id>
requested_outcome: <normalized outcome>
modalities: [call | shell | drive]
constraints: <manual and policy constraints>
inputs: <action inputs from context>
expected_events: <closed event list for this action and state>
required_payload: <fields required for each event>
effect_policy: <read/write and approval gates>
elicitation_contract: <prompt id, selection mode, choices, and harness fallback when a choice may be needed>
evidence_contract: <references that must be returned>
idempotency_key: <stable key for retryable effects>
```

Require one declared event with its complete payload. Reject prose-only completion, unknown events,
missing evidence, or a response for another run/state/action.

Prepare the packet with `scripts/bin/play-handoff prepare --stdin --json`, supplying the rote-* skills
that the current harness actually exposes as callable. If it emits `specialist_unavailable`, enter
`blocked`; do not fall through to an MCP, app, shell, or browser tool.

The specialist must return a `play.handoff-receipt/v1` containing the packet SHA, matching run,
state, action, and owner, `executor.kind: skill`, the declared event and complete payload, and
evidence references. Validate it with `scripts/bin/play-handoff verify --stdin --json` before Play
accepts the event. A raw tool result or a receipt synthesized by Play is invalid.

The portable packet and receipt shapes are declared in
[`../controller/handoff.schema.json`](../controller/handoff.schema.json).

## CALL adapter convergence

A CALL packet includes `capability_policy.kind=rote_adapter`. Treat that policy as a stop condition,
not a suggestion:

1. Search installed Rote adapters and reuse an adequate one.
2. If missing, hand off to `rote-adapter-create`. Detect `openapi`, `graphql`, or `mcp` from the
   provided spec/endpoint, catalog evidence, server card, or provider documentation. MCP uses
   `rote adapter new-from-mcp`; OpenAPI and GraphQL use the dry-run-first `rote adapter new` path.
3. Complete or repair authentication through the Rote creation/configuration flow. Use
   `rote-adapter-config` for an existing adapter, preserve explicit human approval, and use masked
   secret entry. Do not ask Play to handle credentials.
4. Execute the requested capability through `rote-using-adapters`.

Probe hints are non-authoritative discovery metadata. They must never become a Play blocker or an
approval event. If the adapter call is guarded, `rote-using-adapters` returns the exact Rote
`confirmation_required` tool, impact, token, workspace, and evidence as the typed
`confirmation_required` receipt event. After Play binds user approval to those fields, prepare a
new packet and resume the same specialist, workspace, and guarded call with that token. A declined
guard returns no effect and must not be retried.

If any stage cannot complete, return `route_exhausted` with evidence. Do not substitute a direct API
or MCP call. `outcome_ready` additionally requires `route_provenance` recording the adapter id,
detected substrate and evidence, creation/reuse status, auth status/owner, orchestration owner,
`adapter_execute_owner=rote-using-adapters`, and `direct_tool_execution=false`.

## Ownership map

- Adapter discovery and calls: `rote-using-adapters`, with adapter configuration/create skills only
  when capability is absent.
- Local commands, files, logs, and process state: `rote-shell`.
- Active-session browser work: `rote-browse`.
- Multi-step adapter work and durable evidence: `rote-workspace`.
- Flow construction and release: `rote-flow-authoring`.
- Candidate preservation and save gates: `rote-flow-crystallization`.
- First-class registry Play inspection and execution: invoke `rote play inspect` or `rote play run`
  directly; never hand these operations to `rote-flow-run`.
- Registry publication and sharing: `rote-registry`.
- Registry inspection, organization summaries, and grouped Play inventories: `rote-registry`.
- Private organization creation and invitations: `rote-org`.
- Repeated failures: `rote-troubleshooting`.

Specialists may consult their own grammar and guidance, but they may not change Play mode, widen
modalities, grant consent, choose visibility, or select the next machine state.

Play itself may not execute a specialist’s MCP, app, shell, or browser tools during
`explore_execute`. Tool availability is a capability signal for the specialist, never a replacement
for specialist ownership.

## Avoid recursive orchestration

The current top-level `rote` skill searches for flows before routing. Play already performs that
search and consent gate. Do not restart that skill router and repeat discovery. This does not
forbid the purpose-built `rote play` CLI controller, which always takes precedence when it exposes
the required capability.
