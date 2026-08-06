# Play Lifecycle

Use this lifecycle after exploration has produced and verified the requested outcome.

## Crystallize

Prepare a candidate from the evidence chain. Preserve deterministic calls, commands, browser
actions, transformations, assertions, inputs, outputs, approvals, and verification. Preserve a
JUDGE node only under `judge.md`. If the procedure is not reusable, return `not_reusable` and keep
the verified result unpublished.

## Offer to save

Ask the structured `private_public_or_skip` question from `prompts.yaml`; do not replace its labels,
descriptions, selection mode, or events with an improvised free-form prompt.

Do not offer to save before verification and candidate preparation.

- **Private** authorizes authoring, releasing, and registry publication to a private organization.
  If needed, create a private organization whose only initial member is the current user. Private
  never means merely writing a local file.
- **Public** authorizes authoring, releasing, and registry publication under a selected public
  identity or organization. Ask for the owner only when it is ambiguous.
- **Skip** ends with the verified outcome and unpublished local exploration state. Do not author,
  release, publish, or index a Play.

## Capture birth, publish, bind, and index

Immediately after release, capture the owner-private birth certificate described in
[birth.md](birth.md). Capture is one-time and content-addressed by the released Flow fingerprint;
block publication if truthful workspace evidence cannot be captured.

Publish the exact released version with the chosen visibility. Bind the immutable birth object to
the minted exact reference and registry content hash, then index the canonical Playcard locally and
run `rote play inspect <org/name> --json` for the canonical reference. Record the birth SHA,
canonical reference, version, visibility, owner, index reference, and inspect response reference.
If the inspected owner, visibility, or version differs from the authorized publication, block
instead of repairing it silently.

On a matching readback, present a small success readout backed by the inspected JSON. Include the
canonical reference, exact version, visibility, owner, and content hash when present. Then briefly
congratulate the user. Do not congratulate before the readback succeeds.

The index is a discovery cache, not the source of truth. A future outcome request starts at search;
an explicit canonical reference goes directly to `rote play run`. In both cases the Play controller,
not this skill, decides whether local state can be reused or must be converged.

## Social operations

Treat list, inspect, share, organization invitation, role change, and membership removal as
explicit Play management requests. Delegate registry and organization operations to their rote
specialists while preserving normal confirmation, authorization, and receipt behavior. Never
invite or share as an implied consequence of saving.

Use [../awareness/management.md](../awareness/management.md) for organization summaries and grouped Play inventories.
