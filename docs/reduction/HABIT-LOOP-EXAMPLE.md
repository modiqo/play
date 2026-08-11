# Fixture: a habit loop forming

Acceptance narrative for the sidekick core (Phase 2). Maya vibe-codes a web app
daily. Her orbit chores: deploy to staging, smoke the health endpoint, post a
summary to the team's #ship channel. Every play appearance below is annotated
with the machine path and the ledger effect.

## Day 1, morning — play is invisible

> **Maya:** make the onboarding modal feel less clunky — try a spring animation

- `invoke → qualify`: task class `creative/exploratory`. Ledger: empty.
- `search → classify`: no match → `standby_exit`, save hook armed.
- Task settles → `save_judge`: one-off aesthetic tweak, no stable output → no offer.

Maya never sees play. Interventions so far: **0**. This is a feature.

## Day 1, evening — the first save offer

> **Maya:** deploy this to staging, hit the health endpoint, then drop a summary in #ship

- `qualify`: class `build-ship-chore`. `search`: no match → silent standby.
- The agent does the work normally through rote (vercel + slack adapters).
- Task settles → `save_judge`: parameterizable (branch, channel), repeatable
  steps, stable output, plausibly recurring → **worth saving**.

> **play:** That looked repeatable — deploy → health check → #ship summary.
> Save it as a Play? **[Team / Just me / Skip]**

> **Maya:** just me

- `capture_delegate` → rote-flow-crystallization → `maya/ship-and-tell` v0.1.
- **Ledger write (positive scope):** `build-ship-chore → intervene`
  (evidence: user saved here).

One question, one tap. No release ceremony, no certificate, no social copy.

## Day 2 — a wrong guess, and the ledger learns

> **Maya:** let's make the dashboard cards draggable

- `qualify`: `creative/exploratory`. `search`: partial match (60%, a react
  scaffold play). Per threshold policy: **mention-only**, one line, no dialog.

> **play:** (one line) A partially matching play exists (`react-dnd-scaffold`) — say "use it" if wanted.

> **Maya:** not while I'm prototyping

- **Ledger write (explicit):** `creative/exploratory → silent`
  (evidence: user statement, Day 2).
- Play acknowledges once and exits. Every future prototyping request skips
  search narration entirely.

## Day 3 — the loop closes

> **Maya:** ship it to staging again and let the team know

- `qualify`: `build-ship-chore`, ledger prior `intervene`.
- `search`: **full local match** `maya/ship-and-tell` → `use_inspect` →
  `use_run` → `use_verify` → `receipt`. Three boundary interactions total.

> **play:** Ran **ship-and-tell** — the play you saved Monday (2nd use).
> Deploy ✓ · health ✓ · posted to #ship. 47s.

This receipt is the loop-closing moment: the deferred reward from Monday's
"just me" lands, attributed to past-Maya. The mental model flips from "play
interrupts me" to "past-me leaves shortcuts for present-me."

## Day 5 — the cue internalizes

> **Maya:** ship and tell

She now *reaches* for the play by name — the cue moved from play's
intervention into her own head. `qualify` classifies this as an exact play
request → straight to the Use lane. Receipt: "4th use."

## Week 3 — the habit generalizes

> **Maya:** save this one as a play too — call it schema-diff-report

Unprompted save intent: she now thinks in plays. Later she promotes
`ship-and-tell` to Team scope; a teammate's digest surfaces it; its use count
becomes social proof. The learn → teach → learn edge only appears *after* the
private habit exists.

## Loop anatomy

| Element | Run side | Save side |
|---|---|---|
| Cue | outcome-shaped request in an `intervene`-classed task | `save_judge` fires after settled repeatable work |
| Routine | inspect → run → verify (3 yields) | one save question, one tap |
| Reward | minutes → seconds, immediately | **deferred to Day 3's receipt** — which must attribute the save ("the play you saved Monday, 2nd use") |

## Counterfactual (why the ledger is Phase 2 scope)

Without the Day 2 ledger write, play offers scaffolds again on Day 4's
prototyping request, and again on Day 6. By the time Day 3's genuine full
match appears, Maya dismisses reflexively — banner blindness — and the Day 3
receipt, the only moment that can close the loop, never happens. Two wrong
interventions in a muted-worthy class cost the entire product.

## Invariants this fixture pins

1. Creative-class requests with an empty ledger produce zero play surface.
2. A partial match never opens a dialog — one line, at most, ever.
3. An explicit scope statement writes the ledger immediately and is honored
   on the very next request.
4. Save offers cost exactly one question; capture and registry mechanics are
   delegated and silent.
5. The re-run receipt names the save moment and the use count.
6. A saved play's class becomes an `intervene` prior without user configuration.
