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

Publish the exact released version with the chosen visibility. For Public, preserve the Play page
URI and install/bootstrap URI returned by the registry; do not reconstruct them from the canonical
reference. Bind the immutable birth object to the minted exact reference and registry content hash,
then index the canonical Playcard locally and run `rote play inspect <org/name> --json` for the
canonical reference. Record the birth SHA, canonical reference, version, visibility, owner, index
reference, inspect response reference, title, description, content hash, and returned URIs.
If the inspected owner, visibility, or version differs from the authorized publication, block
instead of repairing it silently.

On a matching readback, run `scripts/bin/play-publication --stdin --json` and present its Markdown
exactly once. Include the canonical reference, exact version, visibility, owner, and content hash.
For Public, also include a clickable Play page link whose label carries the title and description,
the install/bootstrap link, and separate fenced plain-text blocks ready to paste into X and
LinkedIn. The X copy must be at most 280 characters; both social blocks must contain the returned
Play URI, and LinkedIn also carries the install URI. For Private, do not produce public URLs or
social copy. These are copy-only outputs: never post or share them implicitly. Then briefly
congratulate the user. Do not congratulate before the readback and presentation succeed.

The index is a discovery cache, not the source of truth. A future outcome request starts at search;
an explicit canonical reference goes directly to `rote play run`. In both cases the Play controller,
not this skill, decides whether local state can be reused or must be converged.

## Social operations

Treat list, inspect, share, organization invitation, role change, and membership removal as
explicit Play management requests. Delegate registry and organization operations to their rote
specialists while preserving normal confirmation, authorization, and receipt behavior. Never
invite or share as an implied consequence of saving.

Use [../awareness/management.md](../awareness/management.md) for organization summaries and grouped Play inventories.
