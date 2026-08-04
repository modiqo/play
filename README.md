# Play

Play is the implicit pre-harness controller for reusable outcomes. It searches authorized Play
indexes first, runs an adequate Play in Use mode, or asks before entering Explore mode. The
existing `rote` and `rote-*` skills remain explicit-only specialists invoked through Play.

## Start here

You do not need to remember organization/name slugs or lower-level rote commands. Describe the
outcome in ordinary language:

```text
$play find a Play that retrieves recent emails
$play run the PostHog daily active users report
$play create a reusable weekly customer report
$play show my digest
$play list my organizations and shared Plays
Handle this normally without Play
```

Play keeps four decisions separate so each prompt is small and honest:

| You intend to… | Play does… | You choose… |
|---|---|---|
| Find something reusable | Search local and authorized organization indexes | Inspect one result or stop |
| Run a known or vaguely named Play | Resolve the name, inspect it read-only, and show setup/effects | Pull and run, or not now |
| Solve a one-off task | Search first; if no adequate Play exists, offer Explore | Explore with rote, or continue normally |
| Preserve successful exploration | Verify it before preparing a candidate | Private, Public, or Skip |
| Keep up with the ecosystem | Compare the current digest with the remembered SHA | Run, search, create, or finish |

Search selection is never execution approval. Before every run, Play shows what the exact version
does, its parameters, adapters and credentials, what this machine must install or repair, declared
operations and writes, and any unknown effect semantics. Only the next structured choice can
authorize the exact inspected version and displayed parameters.

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

## Everyday Play commands

Find by outcome across local and authorized remote indexes:

```text
$play find a Play that retrieves recent emails
$play search live status for AI services
$play run the PostHog DAU report
```

For a vague `run` request, Play searches and offers recognizable names. For an exact reference, it
skips search but never skips inspection or approval. A registry-only result is labeled as available
in an authorized organization and expected to need a local pull/install. The first-class run later
performs that convergence after approval; Play does not manually assemble pull and Flow commands.

List organization and registry inventories:

```text
$play list orgs
$play list plays
$play list
```

Create, explore, save, and share without memorizing lifecycle commands:

```text
$play create a reusable weekly customer report
Explore this with rote and make it reusable if it works
Handle this normally without Play
```

Play always searches before creating. If an adequate Play exists it offers Inspect existing, Adapt
existing, or Create distinct. Otherwise explicit create intent enters Explore directly. Successful
exploration is verified before Play asks:

- **Private** — release and publish to an authorized private organization;
- **Public** — release and publish under a selected public owner;
- **Skip** — keep the result without publishing or indexing a Play.

After Private or Public publication, Play indexes and inspects the canonical version before calling
the save successful. Organization membership, invitations, and sharing use the organization/list
surface rather than hidden local state.

Show an externally read-only awareness digest:

```text
$play digest
$play digest for the last 7 days
scripts/bin/play-digest --remember --days 1 --json
scripts/bin/play-digest --since 2026-08-03T00:00:00Z --json
scripts/bin/play-digest --checkpoint host-checkpoint.json --json
scripts/bin/play-digest --org modiqo --days 7 --json
```

The digest separates newly published Plays from revisions backed by released-version timestamps,
enriches public Plays in authorized organizations through canonical `play inspect` data, and
exposes exact selections that enter read-only inspection before execution approval. Ranking scope and
missing global or personal metrics are explicit rather than inferred. The emitted checkpoint token
can be persisted by an authorized host for gap-free daily delivery; the command does not write host
state unless `--remember` is explicit.

On normal `$play digest` requests, Play uses remembered mode. It stores only a stable awareness SHA,
UTC checkpoint, and authorized-scope contract in `~/.rote/play/digest-state.json`. If the current
snapshot has the same SHA, the next response is simply “Nothing changed since your last Play
digest.” The moving time window is excluded from the SHA, and no digest contents or credentials are
stored.

Recurring delivery is optional and must be explicitly requested. Its host-neutral two-phase
contract remains available for an authorized scheduler:

```bash
scripts/bin/play-scheduler-probe
scripts/bin/play-delivery prepare --target-key daily-self --channel harness --days 1
scripts/bin/play-delivery release --envelope envelope.json --ack delivered-ack.json
```

The host scheduler owns recurrence, destination delivery, and storage. `prepare` emits an immutable
envelope with a deterministic delivery ID; `release` emits the next checkpoint only for a matching
successful acknowledgment and never persists it. Failed sends therefore leave the prior checkpoint
unchanged. Play never installs or fabricates a scheduler as part of an on-demand digest request.

Search normalizes punctuation and repeated terms, runs both sources concurrently, deduplicates
aliases and versions by canonical Play reference, and shows a URI, local availability, and the next
read-only inspection command for every registry-addressable result.

The organization view shows active member, private Play, public Play, and total counts. The Play
view groups private and public Plays under each authorized organization. An ambiguous `$play list`
request presents both views as structured choices supported by the active harness.

For diagnostics or integrations, the same reusable building blocks are available directly:

```bash
scripts/bin/play-search recent emails --json
scripts/bin/play-inspect warsaw-rust/posthog-dau-report@0.0.3 --json
scripts/bin/play-inventory --json
scripts/bin/play-question approve_play_run --harness codex
scripts/bin/play-question approve_play_run --harness claude
scripts/bin/play-question approve_play_run --harness kimi
```

The question command maps the same prompt and event contract to Codex `request_user_input`, Claude
and Kimi `askquestion`, or a numbered Markdown fallback. `play-inspect` normalizes the complete
`rote play inspect <reference> --json` result into a stable disclosure. After approval, the
controller performs exactly one `rote play run <exact-reference> <approved-parameters> --yes`.
It uses `rote flow` or `rote registry flow` only where `rote play` has no equivalent capability and
never decomposes a failed Play operation into a pull-plus-Flow-run fallback.

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
