---
name: play
description: >
  Use before tools or rote specialist skills when a user asks for an outcome that may be fulfilled
  by a reusable procedure. Search local and authorized Play indexes, run an adequate Play, or ask
  whether to explore with rote and preserve a new Play. Also use to search, list, inspect, run,
  create, save, share, or invite people to Plays, including requests constrained to adapters,
  shell, browser, or combinations.
---

# Play

> Think in terms of Plays before thinking in terms of tools.

Treat `play` as the user-facing controller. Treat `rote-*` skills as internal execution owners.
Follow the declarative machine instead of reconstructing its lifecycle from prose.

## Start or resume

1. Read [references/machine.yaml](references/machine.yaml) on every activation.
2. Create a `play.context/v1` record for a new task, or recover the existing record by task key or
   run ID.
3. Validate the context's machine version, current state, transition sequence, and pending action.
4. Execute exactly one declared prompt or entry action for the current state.
5. Accept only an event declared by the current state and validated by
   [references/actions.yaml](references/actions.yaml) or
   [references/prompts.yaml](references/prompts.yaml).
6. Evaluate guards, apply the declared mutation, checkpoint, and then enter the target state.
7. Repeat until `receipt`, `completed`, `exited`, or `blocked`.

Never jump states based on conversational intuition. Never infer completion from a specialist's
prose when its declared return event is absent or invalid.

## Load branch guidance

- Before `explore_route` or `explore_execute`, read
  [references/modalities.md](references/modalities.md).
- Before `crystallize`, `save_offer`, authoring, publication, indexing, sharing, or invitation, read
  [references/lifecycle.md](references/lifecycle.md).
- Before preserving any irreducible inference step, read
  [references/judge.md](references/judge.md).
- Before invoking a `rote-*` specialist, read
  [references/rote-handoffs.md](references/rote-handoffs.md).

Do not load unrelated references.

## Interpret decisions

Use agent reasoning only for the typed evaluators declared in `actions.yaml`:

- qualify the request;
- classify Play adequacy;
- select an allowed modality route;
- verify the requested outcome.

Return the evaluator's declared event and required payload. Explanation may accompany the payload,
but it cannot replace fields, add an event, select a target state, or override a guard.

Controller reasoning is not JUDGE. JUDGE exists only as a declared nondeterministic node inside a
saved Flow when the outcome itself cannot be reproduced deterministically.

## Preserve the two modes

For an adequate authorized match, enter Use:

```text
inspect → preflight → run exact version → verify → receipt → stop
```

Run an exact ready local Play directly. Resolve or pull only when the selected version is missing,
stale, corrupt, or explicitly refreshed. Never silently upgrade the selected version.

For partial, uncertain, or absent matches, ask whether to Explore with rote or continue normally.
Do not execute an exploration modality before approval. If the user continues normally, enter
`exited`, suppress Play re-entry for the same task, and let the ordinary harness proceed.

## Respect policy

- Treat user modality constraints as authoritative.
- Ask before widening CALL, SHELL, or DRIVE.
- Keep JUDGE forbidden unless the policy allows it.
- Keep writes and human gates visible in the delegated runtime.
- Verify the requested outcome before preparing a candidate.
- Ask Private, Public, or Skip only after candidate preparation.
- Treat Private and Public as authorization to author, release, and publish with that visibility.
- Treat Skip as unpublished local exploration state, not a saved Play.
- Treat private as registry-backed organization ownership, never merely a local file.
- Index the exact canonical version after successful Private or Public publication.

## Delegate execution

Build the normalized packet in [references/rote-handoffs.md](references/rote-handoffs.md), select
one existing specialist owner, and require its declared return event. Specialists own commands and
evidence capture; Play owns consent, policy, transitions, and user-facing closure.

Do not call the current top-level `rote` entrypoint from its beginning after Play search. Enter the
post-search continuation or invoke the selected specialist directly, so search and Explore consent
occur exactly once.

## Stop safely

Enter `blocked` when an action or evaluator returns invalid output, authority is missing, a required
modality remains forbidden, an unsafe effect lacks approval, the exploration budget is exhausted,
or machine state cannot be recovered. Report the blocker and evidence without inventing defaults.

At terminal state, present only the outcome relevant to that terminal:

- `receipt`: verified unchanged Use result;
- `completed`: verified Explore result plus saved reference or explicit unpublished status;
- `exited`: confirmation that Play stepped aside for this task;
- `blocked`: missing authority, capability, valid output, or recoverable state.
