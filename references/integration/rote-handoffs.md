# Rote Handoffs

Play owns the user-facing lifecycle. Existing `rote-*` skills own domain execution. Hand off to the
narrowest applicable specialist after Play has selected a state and route.

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

## Avoid recursive orchestration

The current top-level `rote` skill searches for flows before routing. Play already performs that
search and consent gate. Do not restart that skill router and repeat discovery. This does not
forbid the purpose-built `rote play` CLI controller, which always takes precedence when it exposes
the required capability.
