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
  identity or organization. It also authorizes one run of the exact versioned public URI with the
  verified parameters from an isolated `/tmp` directory after associated credential contracts pass.
  Ask for the owner only when it is ambiguous.
- **Skip** ends with the verified outcome and unpublished local exploration state. Do not author,
  release, publish, or index a Play.

## Capture birth, publish, bind, and index

The state boundary is mandatory, not descriptive. Invoke `rote-flow-authoring` for authoring,
testing, linting, and local release only, then require it to return an explicitly `unpublished`
released candidate. Return control to Play and run `birth_capture` before a registry write is
authorized. Only afterward may a new, publication-only `rote-registry` handoff push the exact
released Flow. That handoff carries the captured birth SHA and must echo it unchanged in its
publication receipt. Never delegate author/release/publish as one task.

If authoring returns evidence that it already published the Flow, emit
`publication_boundary_violated` and block. Do not show links, share copy, congratulations, or offer
to manufacture a retrospective birth certificate. The published registry artifact may remain
valid, but it was not born through this controller run.

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

For a matching Public readback, run `scripts/bin/play-publication-gate credentials --stdin --json`
before any link, share copy, or congratulations. For each associated adapter, require the selected
registry source to be among the resolved candidates and the installed adapter to be ready with a
verified provenance receipt. Compare the installed and published adapter version and fingerprint,
then compare auth family and every declared credential environment-variable name against Rote's
resolved credential demand. Matching fingerprints do not excuse a provenance, version,
authentication, or environment-variable mismatch. The gate may retain names such as
`GITHUB_API_TOKEN`; it must never read, hash, print, copy, or persist the corresponding value.

After that contract passes, run `scripts/bin/play-publication-gate smoke --stdin --json`. It invokes
exactly one `rote play run <registry-returned-versioned-uri> <verified-parameters> --yes` from a
fresh temporary working directory under `/tmp`. This removes repository and workspace context from
the smoke test while retaining the current host's installed Rote and credential store. Preserve
only success/failure, bounded classifications, output/error digests, byte count, and elapsed
nanoseconds; never retain the smoke run's primary payload in controller context. A successful run
proves the canonical URI resolves with the current host's credential setup, not that an arbitrary
consumer already has credentials.

Any credential-contract mismatch or public smoke failure blocks presentation. Do not silently pull
or republish an adapter, change `token_env`, authenticate, delete transaction backups, or retry.
Those remediations remain explicit Rote-owned work, after which the publication gates start again
from canonical inspection.

On a matching Private readback, or a Public readback whose credential and smoke gates passed, run
`scripts/bin/play-certificate --stdin --json` and present its Markdown exactly once. The typed
renderer must resolve the immutable owner-local birth object, require its binding to match the exact
reference and registry content hash, and visualize its birth SHA, Flow fingerprint, publication,
human domain expert, and trace learning. Count successes, errors, and unknown outcomes only from
explicit status evidence in the same redacted birth trace; never treat missing status as success.

For Public, include the exact registry-returned Play URI and separate fenced plain-text blocks ready
to paste into X and LinkedIn. The X copy must be at most 280 characters; both social blocks contain
the returned Play URI, and LinkedIn also carries the install URI. For Private, do not produce public
URLs or social copy. These are copy-only outputs: never post or share them implicitly. End with the
safe human handle and the exact sentiment that it was a pleasure working together and that we did
an excellent job. Do not show this closure before readback, binding, and Public gates succeed.
`play_published` is therefore an intermediate event, never permission to end with a registry
summary. The only successful terminal route for a saved Play is
`birth_present → birth_certificate_presented → completed`.

The index is a discovery cache, not the source of truth. A future outcome request starts at search;
an explicit canonical reference goes directly to `rote play run`. In both cases the Play controller,
not this skill, decides whether local state can be reused or must be converged.

## Social operations

Treat list, inspect, share, organization invitation, role change, and membership removal as
explicit Play management requests. Delegate registry and organization operations to their rote
specialists while preserving normal confirmation, authorization, and receipt behavior. Never
invite or share as an implied consequence of saving.

Use [../awareness/management.md](../awareness/management.md) for organization summaries and grouped Play inventories.
