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

1. In `adapter_discover`, hand discovery to `rote-adapter-create` to search installed Rote adapters and inspect
   every plausible match. Reuse a unique adequate one; present multiple plausible adapters.
2. If no installed adapter is adequate, always run
   `rote adapter catalog search <adapter_discovery.query> --json`. Present every result through
   `adapter_offer`; REST/OpenAPI, GraphQL, and MCP entries for the same provider are separate choices.
3. After a selection, successful zero-result catalog search, or explicit rejection, enter
   `adapter_converge` and hand the complete discovery record back to `rote-adapter-create`. That
   specialist owns spec inspection, dry-run, creation, initial authentication, and readiness; Play
   must not reproduce those steps. It may inspect a supplied spec/endpoint, server card, or provider documentation.
   Detect `openapi`, `graphql`, or `mcp` from that ordered evidence. MCP uses
   `rote adapter new-from-mcp`; OpenAPI and GraphQL use the dry-run-first `rote adapter new` path.
4. Complete initial authentication through the Rote creation flow. For a recoverable failure on an
   existing adapter, return the typed authentication request described below. Do not ask Play to classify
   authentication or handle credentials.
5. Only an `installed_ready` convergence receipt may prepare the execution packet. Execute the
   requested capability through `rote-using-adapters`.

The CALL packet binds the typed `adapter_discovery` record. Missing installed-inventory evidence,
catalog fallthrough without catalog evidence, an unselected match, or reordered discovery is an
invalid handoff rather than permission to improvise.

Probe hints are non-authoritative discovery metadata. They must never become a Play blocker or an
approval event. If the adapter call is guarded, `rote-using-adapters` returns the exact Rote
`confirmation_required` tool, impact, token, workspace, and evidence as the typed
`confirmation_required` receipt event. After Play binds user approval to those fields, prepare a
new packet and resume the same specialist, workspace, and guarded call with that token. A declined
guard returns no effect and must not be retried.

If any non-recoverable stage cannot complete, return `route_exhausted` with evidence. Do not
substitute a direct API or MCP call. `outcome_ready` additionally requires `route_provenance`
recording the adapter id,
detected substrate and evidence, creation/reuse status, auth status/owner, orchestration owner,
`adapter_execute_owner=rote-using-adapters`, and `direct_tool_execution=false`.

## Recoverable authentication

Saved Play authentication is selected from the inspected operations. When a Play declares
`adapter.auth.ensure`, the approved `rote play run` owns browser-capable provider sign-in: Play
re-enters that same command with terminal-backed stdin at an exact pre-call browser boundary and
does not delegate it. A failed Play-owned browser authentication step blocks with its exact output.
A typed missing static credential is the exception: the harness may enter `rote-adapter-config`,
resolve only the adapter catalog's first-party HTTPS `token_url`, and present the vendor page plus
`rote token set <ENV> --stdin` for the user to run in their own terminal. The harness never receives
the credential. After the user confirms and the named token is verified, the exact approved Play is
inspected and run again. A legacy Play without `adapter.auth.ensure` may also offer the compatibility
path. This path does not manufacture an authentication receipt.

Before any Play run, bind the exact reference, parameters, disclosure SHA, and expected events into
`play.run-handoff/v1` with `scripts/bin/play-handoff prepare-play-run --stdin --json`. Preserve that
packet and SHA as the original contract; do not expand the Play run into adapter commands.

The closed authentication packet and receipt contract below is retained for uncovered CALL
handoffs. It is not the saved-Play authentication path.

Do not collapse a recoverable CALL authentication failure into `route_exhausted`. The execution
owner returns `authentication_required` with `source=rote_authentication_required`, `recoverable=true`, the
adapter id, environment variable name, opaque classified rung, distinguishing error, and evidence.
The packet must not contain a token, secret, credential value, or other undeclared field.

After Play receives explicit approval, prepare `play.authentication-handoff/v1` with
`scripts/bin/play-handoff prepare-authentication --stdin --json`. This is a separate closed handoff to
`rote-adapter-config`; it neither adds that skill to the CALL execution owner set nor authorizes the
provider operation. Bind the authentication packet to the exact original CALL packet and SHA.

Rote `0.69.2` and newer own missing OAuth DCR credential bootstrap in place. For a classified OAuth,
OAuth DCR, or Google discovery boundary, `rote-adapter-config` runs
`rote adapter reauth <adapter-id>` against the installed adapter. Never pack, delete, recreate, or
run `new-from-mcp` for this condition: successful reauthorization preserves the manifest,
fingerprint, selected tool inventory, provenance, and dependent-Play indexing.

Static credentials remain an explicit local `rote token set <env-var> --stdin` flow. If the installed
adapter does not declare enough setup metadata to distinguish static bearer authentication from a
portable OAuth protocol, fail closed with Rote's exact remediation instead of guessing. After either
protocol-specific path, require fresh adapter health evidence before the original Play may resume.

Require `play.authentication-receipt/v1` and validate it with
`scripts/bin/play-handoff verify-authentication --stdin --json`. A successful receipt must match the
requested adapter, environment variable, and classified rung, name the authentication action, and include
evidence. A declined, unavailable, failed, mismatched, or malformed authentication enters `blocked`.

After validated authentication, invalidate the prior execution packet and prepare a fresh
`play.handoff/v1` packet for the original owner. Preserve the original requested outcome,
modalities, constraints, inputs, effect policy, evidence contract, and idempotency key; attach only
the original packet SHA, authentication receipt reference, adapter id, and classified rung as resume
provenance. The original CALL must execute and pass normal receipt and outcome verification.

## Play-request setup handoff

Any `$play` or `/play` request may hand off to `rote-setup` after typed live preflight reports the
binary missing, or reports a structurally healthy installation whose only failed check is an
unauthenticated identity. This is normal onboarding, not an Explore execution owner, a CALL
authentication packet, or an installation-error presentation. Preserve the original request
and opaque continuation while setup runs.

Pass the onboarding intent, live Rote status, resolved command when present, and expected closed
events. `rote-setup` owns its sequential binary/state probes, install choice, remote-code approval,
login, and optional remaining onboarding. Play must not inline an installer or login command. Accept
only `rote_setup_completed`, `rote_setup_paused`, or `setup_specialist_unavailable` with the declared
payload. A completed result reruns the complete live preflight rather than trusting a prose success
claim, then resumes the original declared event. A pause preserves the request and gives its
recovery direction; an unavailable specialist remains a real blocker.

## Ownership map

- Adapter discovery and calls: `rote-using-adapters`, with `rote-adapter-create` when capability is
  absent and the separate approved `rote-adapter-config` handoff for recoverable authentication.
- Local commands, files, logs, and process state: `rote-shell`.
- Active-session browser work: `rote-browse`.
- Multi-step adapter work and durable evidence: `rote-workspace`.
- Flow construction and release: `rote-flow-authoring`.
- Candidate preservation and save gates: `rote-flow-crystallization`.
- First-class registry Play inspection and execution: invoke `rote play inspect` or `rote play run`
  directly; never hand these operations to `rote-flow-run`.
- Registry publication and sharing: `rote-registry`.
- Registry inspection, organization summaries, and grouped Play inventories: `rote-registry`.
- Play onboarding when Rote is missing or unauthenticated: `rote-setup`.
- Private organization creation and invitations: `rote-org`.
- Repeated failures: `rote-troubleshooting`.

## Save-lifecycle boundary

Do not reuse the Explore execution packet or send one broad task across release and publication.
For `author_release`, invoke only `rote-flow-authoring`, scope the request to author/test/lint/local
release, and require an explicitly unpublished released candidate. A receipt that contains a
registry reference or says publication already occurred maps to
`publication_boundary_violated`, not `flow_released`.

After Play captures `birth.sha256` and `birth.capture_ref`, invoke `rote-registry` separately for
`private_publish` or `public_publish`. Its inputs include the exact released Flow, visibility/owner
consent, and captured birth receipt; its `play_published` payload must echo that birth SHA. Reject a
mismatch and do not proceed to binding. Neither specialist may select the next state or provide the
terminal user-facing publication response.

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
