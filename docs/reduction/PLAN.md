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

## Decision memory: the preference ledger

The habit loop dies without memory. Every intervention play makes — run offer,
save offer — produces a user decision, and every decision carries scope. A user
who says "I don't want plays during vibe coding, I want plays for the workflows
around it" has expressed a per-task-class policy, not an on/off switch. Play
must remember decisions at that granularity or it trains users to dismiss it.

Design:

- **Ledger, not config.** An owner-private, human-readable ledger under
  `~/.rote/play/preferences` holding scoped entries:
  `(task_class, policy, evidence, timestamp)` where policy ∈
  {intervene, mention_only, silent} and evidence is the decision that created
  the entry (explicit statement or accumulated dismissals). No upfront
  configuration screen — the ledger is learned.
- **Qualify consults the ledger.** The qualification evaluator's input gains
  the matching ledger entries. A `silent`-classed request skips search and
  narration entirely and exits without a trace; `mention_only` allows a
  one-line surface but never a dialog. The ledger is a prior, and the
  evaluator may override it only for an exact saved-play invocation by the
  user.
- **Dismissals write, they don't just exit.** `search_dismissed`,
  `play_run_declined`, and `save_skipped` events gain an optional scope
  payload. An explicit statement ("no plays when I'm prototyping") writes a
  ledger entry immediately; repeated unexplained dismissals in the same task
  class (2–3) write a `mention_only` downgrade automatically, with a
  presentation telling the user it happened and how to undo it.
- **Saves write positive scope too.** A saved play's task class becomes an
  `intervene` prior — the classes a user saves in are the classes they want
  play active in. The ledger converges toward the user's actual orbit of
  repeatable work without anyone configuring it.
- **Visible and revocable.** The management trajectory gains a `play prefs`
  view: list ledger entries with their evidence, delete or flip any of them.
  Silent muting without inspectability would be worse than no muting.
- **Machine cost is near zero.** No new interception states — the existing
  decline events gain payload fields, qualify/classify gain a ledger input,
  and one deterministic action reads/writes the ledger file. This is Phase 2
  scope, not a later phase: the ledger must exist before the save hook ships,
  because the first weeks of dismissals are exactly the signal that teaches
  play where to stand.

### Preference tiers

Preferences are keyed `(scope, task_class) → policy` with three scopes and
strict precedence: **session > project > global**.

- **Session** ("stay out of my way today"): an overlay held in run/session
  state, never written to the durable ledger, dies with the session. Cheapest
  to honor, cheapest to get wrong.
- **Project**: keyed by repo/workspace root. Vibe-coding-heavy repos and
  ops-heavy repos deserve different defaults; ledger evidence records the cwd
  so this tier can be inferred, not configured.
- **Global**: the durable ledger entries described above.

Promotion is observed, not asked: a session mute for the same class in ~3
consecutive sessions silently promotes to the durable tier with a one-line
notice and an undo path — a promotion question would itself be an
intervention. All tiers are visible in `play prefs`.

### The two classifiers (and why neither is a skill)

Both judgments are **model-evaluator boundaries inside the machine**, with
rubrics delivered state-locally via the projection — not separate skills.
A classifier SKILL.md would recreate the read-before-act tax the reduction
exists to remove.

1. **Qualify-time classifier** (runs on every request, must be near-free):
   two-stage. A deterministic gate first — exact play-name/URI match, ledger
   hit on an unambiguous verb class, conversation shapes — resolves the
   common cases with no model call (the existing deterministic fast lane,
   generalized). Only ambiguous requests reach the model evaluator, whose
   output is `(task_class, intervention_decision)` with the ledger tiers as
   priors.
2. **save_judge** (runs once, after settled work): judges the **trace, not
   the conversation**. The rote workspace DAG and cached `@N` responses are
   its evidence: parameterizable inputs are literals in the trace that would
   vary next time (branch, channel, date); repeatable steps are an
   effect-bearing step sequence without human improvisation forks; stable
   output is a typed final artifact. Rubric gates, all required early:
   ≥2 effect-bearing steps, ≥1 identifiable parameter, a stable output
   contract, and a recurrence prior (similar past work, or explicit user
   signal). Negative gates: never offer after a failed or abandoned task,
   and never for work in a `silent`-classed session regardless of scores.

The task-class taxonomy stays coarse — on the order of five classes
(creative/exploratory, build-ship chore, data-fetch/report, ops/maintenance,
conversation) — so a handful of decisions per class is enough evidence to
learn from. A fine ontology would never converge.

## The SKILL.md contract shrinks with the machine

Target ≤ 60 lines: how to enter (`run-until-yield`), the four boundary types,
how to resume with one typed event, fail-closed rules, terminal presentation.
Every state-local policy paragraph currently hoisted into SKILL.md (publication
boundaries, birth rules, auth-repair packets, what never to print) moves into
the projection payloads of the states that need it — that is the load-bearing
promise of the runtime, and it is what removes the read-before-act tax.

## Sequencing

1. **Phase 0 (done)** — plan + target contract draft.
2. **Phase 2 (done, commit 1690fb0)** — cut explore orchestration and its
   auth-repair duplicate (87 → 70 states), add `standby_exit`, `save_judge`,
   settle re-entry, the preference ledger, and the 74-line SKILL.md.
3. **Phase 3 — removal, not relocation.** The remaining lanes are play
   re-implementing orchestration the rote skills already own; delete them and
   defer:
   - Onboarding + team (19 states) → one probe-and-present action; setup
     stays with `rote-setup`, team spaces and invites go to `rote-org`.
     Orientation survives as a presentation, not a trajectory.
   - Publication chain (15 states) → `save_offer` → one `save_delegate`
     specialist handoff (`rote-flow-crystallization` / `rote-flow-authoring` /
     `rote-registry` run their own flow) → `saved_present` receipt
     validation. Birth capture stays as a deterministic wrapper around the
     handoff (capture before, verify canonical readback after); `birth_show`
     stays as an explicit request. Play validates typed receipts instead of
     supervising steps.
   - Creator lane (4 states) → the no-match path with the hook pre-armed.
   - Management (3 states) → `rote-registry`; play keeps only `play prefs`.
   - Awareness 4 → 2 (genuinely play's: cards, digest cache, trending).
   Target: ~30 states, each either on the interception path or a typed
   receipt boundary. The trade, accepted deliberately: play trusts rote
   specialists' internal quality and enforces only packet/receipt integrity.
4. **Phase 4 — retire orphaned surfaces.** Dead `play-*` bin scripts,
   references, prompts, and validator invariants the removals strand.
5. **Phase 5 (separate track) — runtime convergence.** Port surviving `play-*`
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
- **Digest/trending surface.** Awareness stays as an explicit trajectory; the
  proactive surface is built as a zero-token cache (below), with the decision
  of *when* to show it deferred until the ledger has real data.

## The zero-token inbox (`play-inbox`)

The what's-new loop must never cost tokens or latency at the moment of recall.
`scripts/bin/play-inbox` implements stale-while-revalidate over the existing
digest collector:

- `play-inbox refresh [--if-older-than H]` — the background-job body. Fetches
  the digest (honoring the awareness lane's acknowledgment checkpoint without
  advancing it), precomputes a one-line summary, and atomically writes both
  tiers to `~/.rote/play/inbox-cache.json`: `summary_line` + `counts` for the
  banner, `digest` + rendered `markdown` for detail recall.
- `play-inbox line` — instant, read-only, prints the one line or nothing.
  Quiet inbox = empty output, so a hook can inject it unconditionally.
- `play-inbox details` — the cached full inbox, no network.

Session-start wiring (SWR, no daemon or cron needed): a SessionStart hook runs
`play-inbox line` (instant, serves the previous refresh) and then kicks
`play-inbox refresh --if-older-than 6` in the background for next session.
Freshness tracks usage; zero model tokens are spent except the one injected
line. The line goes quiet after the user actually views the digest, because
the interactive awareness lane owns the acknowledgment checkpoint and the
refresh only reads it.
