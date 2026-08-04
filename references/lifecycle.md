# Play Lifecycle

Use this lifecycle after exploration has produced and verified the requested outcome.

## Crystallize

Prepare a candidate from the evidence chain. Preserve deterministic calls, commands, browser
actions, transformations, assertions, inputs, outputs, approvals, and verification. Preserve a
JUDGE node only under `judge.md`. If the procedure is not reusable, return `not_reusable` and keep
the verified result unpublished.

## Offer to save

Ask exactly:

> Save this Play as Private, Public, or Skip?

Do not offer to save before verification and candidate preparation.

- **Private** authorizes authoring, releasing, and registry publication to a private organization.
  If needed, create a private organization whose only initial member is the current user. Private
  never means merely writing a local file.
- **Public** authorizes authoring, releasing, and registry publication under a selected public
  identity or organization. Ask for the owner only when it is ambiguous.
- **Skip** ends with the verified outcome and unpublished local exploration state. Do not author,
  release, publish, or index a Play.

## Publish and index

Publish the exact released version with the chosen visibility. Then index the canonical Playcard
locally. Record canonical reference, version, visibility, owner, and index reference. If visibility
or version differs from the authorized choice, block instead of repairing it silently.

The index is a discovery cache, not the source of truth. A future request starts at search. When an
exact indexed local version is ready, run it directly; resolve or pull only when it is missing,
stale, corrupt, or explicitly refreshed.

## Social operations

Treat list, inspect, share, organization invitation, role change, and membership removal as
explicit Play management requests. Delegate registry and organization operations to their rote
specialists while preserving normal confirmation, authorization, and receipt behavior. Never
invite or share as an implied consequence of saving.
