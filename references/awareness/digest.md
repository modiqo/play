# Play Awareness Digest

Use this guidance for daily or weekly digests, new or revised Plays, top public Plays, and personal
impact summaries. Awareness is read-only and precedes Use; do not merge it into execution.

## Collect

Use `scripts/bin/play-digest --days <n> --json`. Require `play.digest/v1`, `complete: true`, an
explicit time window, authorized organization results, and a declared public ranking metric.

- New means first publication occurred inside the window.
- Revised means a newer released version occurred inside the window.
- Do not treat a visibility-only metadata edit as a revision.
- Include private Plays only from organizations authorized for the current identity.
- Describe public results as trending only when the metric is windowed usage. Lifetime totals must
  be labeled most downloaded overall.
- Report unavailable personal metrics as unavailable, never as zero.

## Present

Show compact New, Revised, Public, and Your impact sections. Each actionable card must carry the
canonical reference, owner, visibility, version when known, and displayed parameters.

Use the `select_awareness_action` elicitation. Selecting Run authorizes only the exact displayed
reference and parameters. Selecting Describe a need enters normal Play search. Selecting Create a
Play enters creator discovery.

The skill cannot invent a scheduler or persist a daily delivery cursor. Automatic delivery needs
an authorized host hook or registry-backed per-user checkpoint. `$play digest` remains the safe
explicit entrypoint.
