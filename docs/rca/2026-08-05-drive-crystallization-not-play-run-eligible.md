# RCA: Browser-extraction Play published despite failing the canonical runner

- **Date of incident:** 2026-08-05
- **Artifact:** `daily-chores/modiqo-pricing-grid@0.0.1` (public registry push, later deleted)
- **Status:** Remediated — version deleted (tombstone `efd5de63-66b9-4747-aaa5-f901fccc444a`, restorable); guidance updated; publication gate added
- **Severity:** Medium — no data loss or security impact; a public consumer running the advertised URI hit a hard error

## Summary

A Play crystallized from a DRIVE (browser) exploration — scraping a hash-routed SPA pricing grid —
was published to the public registry even though the registry marked it
`play_run_eligible: false`. Any consumer invoking the first-class surface,
`rote play run https://play.modiqo.ai/daily-chores/modiqo-pricing-grid@0.0.1`, received:

```
error: Play resolution failed: play is not executable through `play run`:
legacy stepless is not supported by play run
```

The play worked correctly through its legacy runner (`rote deno run`), passed lint, and passed
three live replay tests — but none of that QA exercised the surface public consumers actually use.

## Impact

- The public URI advertised a Play that errored at resolution for every `rote play run` consumer.
- The user discovered the failure themselves and had to report it.
- Trust cost: a "released, published, congratulated" artifact did not meet rote's own
  first-class-command guideline.

## Timeline (2026-08-05)

1. User requested a pricing-grid scrape via parallel-cli; the shell route was exhausted
   (parallel-cli strips SPA hash fragments) and the user approved widening to DRIVE.
2. Browser exploration succeeded; outcome verified; user chose **Public** at `save_offer`.
3. Crystallization found the grid's cell values unreachable through typed extract slices
   (`clickable|links|headings|forms|errors` carry no arbitrary cell text; no `browser.snapshot`
   step type exists), so the play was authored as a **legacy stepless body**.
4. QA: `rote play lint` passed; three distinct-input replays via `rote deno run` succeeded.
5. Registry push succeeded and returned `play_run_eligible: false` with blocker
   "legacy stepless is not supported by play run". This was disclosed as a footnote, not treated
   as a gate.
6. User ran `rote play run <uri>`; resolution failed; user reported it.
7. Version deleted from registry (recoverable); play retained locally.

## Root causes

1. **Platform capability gap (necessary condition).** The typed step language cannot represent
   raw-snapshot or arbitrary DOM/table extraction. Front-end accessibility trees are volatile and
   site-specific, so rote's canonical slices deliberately project only bounded element classes —
   which excludes the very facts (prices, entitlement cells) this outcome required. Such browser
   outcomes can only crystallize as legacy stepless bodies in the current version.
2. **Legacy stepless bodies are not `rote play run`-eligible.** The canonical runner rejects them
   by design; only `rote deno run` replays them.
3. **Process failure (proximate cause).** `play_run_eligible: false` in the push response was
   treated as a disclosure item rather than a release gate. QA validated the play's own execution
   model but never smoke-tested the published artifact through `rote play run`.
4. **Missing early warning (user-experience cause).** Nothing in the Explore consent or DRIVE
   routing flow warned that a browser-extraction outcome would likely be non-crystallizable as a
   runnable Play. The user learned the limitation only after publication — after the
   Private/Public/Skip decision had already been made on incomplete information.

## Remediation

| # | Action | Status |
|---|--------|--------|
| R1 | Delete `@0.0.1` from the registry (recoverable tombstone); keep the play local-only | Done |
| R2 | Memory gate: `play_run_eligible: false` is a publication gate requiring explicit user approval; post-publish readback must smoke-test `rote play run` resolution | Done |
| R3 | **Pre-exploration warning** (this RCA's driver): `references/explore/modalities.md` now carries a "DRIVE crystallization limit" section, and SKILL.md requires the Explore offer to surface it whenever the route includes DRIVE and the outcome depends on page content beyond the canonical slices | Done |
| R4 | Re-author as a typed `steps:` play and republish if/when rote adds a raw-snapshot or richer extract step | Deferred — blocked on platform capability |

## Prevention: the warning users now see

Before a DRIVE exploration whose outcome depends on extracting arbitrary page content (tables,
grids, free text), Play must state, at the Explore offer or DRIVE route milestone, to the effect
of:

> Heads-up: in this version, browser extractions like this generally cannot be crystallized into
> a runnable Play — typed steps cannot capture arbitrary front-end content, which is volatile
> across sites and releases. If the exploration succeeds, the result can be kept as a verified
> outcome or preserved as a local legacy Flow (replayed with `rote deno run`), but it cannot be
> published as a `rote play run`-eligible Play.

And at `save_offer`, the limit is repeated so Private/Public/Skip is decided with full knowledge.

## Lessons

- A registry response field that names a blocker on the canonical execution path is a gate, not
  metadata.
- QA must cover the surface consumers are told to use, not only the surface the author used.
- Constraints discovered mid-exploration that change what "saving" means must be surfaced before
  consent decisions, not after publication.
