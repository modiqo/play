# Play

Play is the implicit pre-harness controller for reusable outcomes. It searches authorized Play
indexes first, runs an adequate Play in Use mode, or asks before entering Explore mode. The
existing `rote` and `rote-*` skills remain explicit-only specialists invoked through Play.

## Enable

Preview every harness root and canonical rote skill that will change:

```bash
just plan
```

Activate the Play-first profile and verify it:

```bash
just install
just verify-profile
```

After editing the source skill, confirm that every source-linked installation is still valid:

```bash
just update
```

The links make source edits live immediately; a running harness must still be restarted to reload
the revised skill.

`install` discovers every installed harness skill root containing `rote` or `rote-*`, links this
Play skill into each root, and makes the rote skills explicit-only. It snapshots the original rote
activation files so the change is reversible. Restart running harnesses after enabling the profile.

Inspect the active profile at any time:

```bash
just status
just status-roots
```

## Start and test a fresh harness

Start a supported interactive harness after verifying the profile:

```bash
just harness codex
just harness claude
just harness kimi
```

Start a compact Codex session without changing global Codex configuration:

```bash
just harness-quiet
```

This launch sets `model_verbosity="low"`, `model_reasoning_summary="none"`, and
`hide_agent_reasoning=true` as per-session overrides. It reduces model narration and reasoning
events; the Codex UI may still render tool calls that were actually made.

Run a read-only smoke test that must reach Play's Explore-or-continue consent gate:

```bash
just smoke codex
just smoke claude
just smoke kimi
```

Run every locally installed supported smoke-test harness with:

```bash
just smoke-all
```

Smoke tests start new harness processes and may consume model credits.

## Manage Plays

The explicit `$play` surface supports organization and registry inventories:

```text
$play list orgs
$play list plays
$play list
```

Search local and authorized registry Plays together:

```text
$play search live status services AI models infrastructure latency
```

Show a read-only awareness digest:

```text
$play digest
$play digest for the last 7 days
```

The digest separates newly published and revised Plays in authorized organizations, truthfully
labels public ranking metrics, and exposes exact Play selections that can enter Use without a
second redundant approval. Personal metrics are shown only when the registry can attribute them;
missing metrics are reported as unavailable rather than zero.

Search normalizes punctuation and repeated terms, runs both sources concurrently, deduplicates
aliases and versions by canonical Play reference, and shows a URI plus the next `rote play run`
command for every registry-addressable result.

The organization view shows active member, private Play, public Play, and total counts. The Play
view groups private and public Plays under each authorized organization. An ambiguous `$play list`
request presents both views as structured choices supported by the active harness.

`rote play` is the first-class command surface. For example, an exact registry Play request runs
through its lifecycle-owning controller in one operation:

```bash
rote play run warsaw-rust/hn-top-comments --yes
```

Play uses `rote play inspect <reference> --json` for inspection. It uses `rote flow` or
`rote registry flow` only where `rote play` has no equivalent capability; it never decomposes a
failed `rote play` operation into a pull-plus-Flow-run fallback.

After a new Play is published and indexed, Play reads the canonical registry entry back with JSON
inspection, verifies its owner/version/visibility, and only then reports success.

## Disable

Remove Play from every managed harness root and restore the exact original rote activation files:

```bash
just uninstall
just status
```

Restart running harnesses after disabling the profile. Uninstall fails closed if a managed Play
link was replaced or a rote activation file changed after installation; it will not overwrite the
newer content silently.

## Development checks

```bash
just test
```

The tests exercise the declarative Play machine and the complete activation lifecycle in temporary
harness roots, including installation, verification, idempotency, rollback, and conflict handling.

The foundation is Python-only. Commands under `scripts/bin/` and harness entrypoints under
`scripts/harness/` are thin executables; reusable command, registry, search, inventory, digest,
elicitation, and machine-validation logic lives in `scripts/lib/play/`. References and tests are
grouped by controller, awareness, Explore, publication, integration, and harness use case.

For isolated testing, override the discovered roots or reversible state location:

```bash
PLAY_HARNESS_ROOTS=/path/one:/path/two just install
PLAY_PROFILE_STATE=/tmp/play-profile.json just install
```
