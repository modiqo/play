# Reduction plan: Play as the sidekick that makes Rote a daily habit

## Product definition (the whole product, stated once)

Play intervenes at exactly two moments and is invisible everywhere else:

1. **Before work** — when the user asks for an outcome, Play searches local and
   authorized hub indexes. If an adequate saved Play exists, it offers to run it.
   If none exists, Play steps aside and lets the task proceed normally.
2. **After work** — when a task that proceeded normally turns out to be
   complicated and repeatable, Play recommends saving it as a Play (delegating
   capture to rote). If the task was one-off, Play says nothing.

Everything else — onboarding, team spaces, digests, birth certificates,
publication verification — is either an explicit-request trajectory or a
delegation to a rote specialist. None of it may sit on the interception path.

## The design shift this encodes

The current machine makes Play the *orchestrator of exploration*: it routes
modalities, dispatches specialists, discovers adapters, manages effect and
auth-repair approvals, and verifies outcomes — 23 states of doing rote's job
with extra ceremony. The sidekick model inverts this: **rote (or the agent
working normally) owns the work; Play owns only the two intervention
moments.** "Stay out of the way" is a feature requirement, not a tone note.

Consequences:

- The explore lane (`explore_welcome` → `explore_verify`, adapter discovery,
  modality/effect offers, explore-side auth repair) leaves the machine.
  No-match no longer forces an explore-consent dialog; it exits quietly with a
  post-task save hook armed.
- The save chain shrinks to: verified-candidate detection → one save offer →
  delegate to `rote-flow-crystallization` / `rote-registry` → present the
  returned reference. Release/publish/smoke/birth mechanics belong to the
  specialists and the registry, not to Play states.
- Auth repair collapses from 8 states (two duplicated 4-state chains) to a
  single "report + delegate to `rote-adapter-config` + retry once" transition.

## Target machine: ~20 states

```
invoke ──┬─ conversation / excluded ───────────────────────────► exited
         ├─ outcome request ─► search ─► classify ─┬─ adequate ─► use_inspect
         │                                         │              ├─ parameter_offer ─┐
         │                                         │              ▼                   │
         │                                         │            use_offer (remote only)
         │                                         │              ▼
         │                                         │            use_run ─► use_verify ─► receipt
         │                                         │              └─ auth failure ─► repair_delegate ─► use_run (once)
         │                                         └─ no/partial ─► standby (arm save hook) ─► exited
         ├─ explicit /play, URI, digest, manage ──► trajectory dispatch (separate machines)
         └─ post-task re-entry ─► save_judge ─┬─ worth saving ─► save_offer ─► capture_delegate ─► saved
                                              └─ one-off ──────────────────────► exited
```

Kept states (≈20): `invoke`, `search`, `search_present`, `search_offer`,
`classify`, `use_inspect`, `use_decide`, `use_parameter_offer`, `use_offer`,
`use_prepare`, `use_run`, `repair_delegate`, `use_verify`, `use_receipt`,
`standby_exit`, `save_judge`, `save_offer`, `capture_delegate`, `saved_present`,
terminals (`receipt`, `completed`, `exited`, `blocked`).

Model boundaries drop from five evaluator families to four: qualification,
adequacy, outcome verification, and the new save-worthiness judgment.

## What moves where

| Current lane (states) | Disposition |
|---|---|
| Explore orchestration, adapter discovery, modality/effect offers (15) | **Cut.** Rote skills own exploration; Play arms the save hook and exits. |
| Explore-side auth repair (4) | **Cut** (duplicate). |
| Use-side auth repair (4) | **Collapse to 1** delegate-and-retry state. |
| Release → publish → birth → index → smoke (13 of the save chain) | **Delegate** to `rote-registry` / rote CLI. Play presents the receipt the specialist returns. Birth certificate becomes an explicit request (`birth_show` stays as a dispatch target). |
| Onboarding + team invites (19) | **Separate machine** (`machine.onboarding.yaml`), entered only via empty `/play`, Play URI, or first-use detection. Never on the interception path. |
| Awareness/digest (4), creator (4), management (3) | Creator collapses into search/classify (create intent = no-match path with save hook pre-armed). Awareness and management become explicit-request trajectory dispatches. |

## The SKILL.md contract shrinks with the machine

Target ≤ 60 lines: how to enter (`run-until-yield`), the four boundary types,
how to resume with one typed event, fail-closed rules, terminal presentation.
Every state-local policy paragraph currently hoisted into SKILL.md (publication
boundaries, birth rules, auth-repair packets, what never to print) moves into
the projection payloads of the states that need it — that is the load-bearing
promise of the runtime, and it is what removes the read-before-act tax.

## Sequencing

1. **Phase 0 (this commit)** — plan + target contract draft (`SKILL.next.md`).
2. **Phase 1 — carve out onboarding.** Move the 19 onboarding/team states to
   their own machine with a dispatch edge from `invoke`. No behavior change;
   pure extraction. Aligns `actions.yaml`, `prompts.yaml`, `context.schema.json`,
   tests.
3. **Phase 2 — cut explore, arm the save hook.** Remove the explore lane and
   its auth-repair duplicate; add `standby_exit`, `save_judge`, and post-task
   re-entry. This is the behavior change and the heart of the sidekick model.
4. **Phase 3 — collapse the save chain.** Delegate release/publish/birth/smoke
   to specialists; keep one offer and one receipt presentation.
5. **Phase 4 — shrink SKILL.md** to the ≤60-line contract once projections
   carry state-local policy. Retire dead references, actions, prompts, and the
   `play-*` bin scripts the cut states orphan.
6. **Phase 5 (separate track) — runtime convergence.** Port surviving `play-*`
   helpers into `rote play …` subcommands so one binary owns identity, search,
   inspection, and the registry. The skill layer does not block on this.

## Open questions

- **Post-task re-entry mechanics.** The save hook fires after work Play did not
  orchestrate. Cleanest trigger: the rote orchestrator's existing Reuse Triage
  Gate invokes Play's `save_judge` instead of its own crystallization prose —
  which also removes the duplicated one-off-vs-repeatable logic from the rote
  skill. Requires a matching edit in the rote skill set.
- **Adequacy threshold.** "Intervene to run what was saved" must not become
  "interrupt every task with weak matches." classify should demand a full match
  to interrupt; partial matches go to standby silently or to a single-line
  mention, not a dialog.
- **Digest/trending surface.** Awareness stays as an explicit trajectory for
  now; whether it deserves proactive surfacing (e.g., session-start digest) is
  a later product decision, not part of the reduction.
