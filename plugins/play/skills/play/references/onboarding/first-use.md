# First-use Play orientation

Use this guidance only after an empty `$play` or `/play` invocation has live-verified an installed,
authenticated Rote identity. Keep canonical URI onboarding separate.

## Identity entrance

Every Play request is identity-gated, including `whats new`. If live preflight is structurally
healthy and only the `authenticated` check is false, this is normal onboarding—not an error path.
Keep the original request and continuation intact, hand off to `rote-setup`, and offer Google or
GitHub sign in/account creation. After the browser flow, require a live `rote whoami`, rerun the
complete preflight, and continue the original request. A paused login explains how to resume; it
must not be relabeled as an installation failure.

Repair activation before evaluating identity. A managed launcher that names a missing recorded
Play source may migrate to the currently loaded marketplace source. Never take over a different
source that still exists, and never ask login to compensate for a broken launcher.

## Promise

Lead with: **Start small. See what happens. Stay in control.**

Explain these facts in plain language:

- A Play is a checked, reusable way to get a result.
- Rote inspects and runs Plays on the user's computer.
- Hello is the recommended low-risk proof: public data, no account, no credentials, and no
  declared writes.
- Play searches for an existing method before starting new exploration.
- If none fits, the human and agent work out the job together.
- The agent brings broad knowledge, search, tool use, and testing.
- The human is the domain expert because only they know the local goals, rules, exceptions,
  standards, history, and judgment that make the result right.
- The human can watch, correct, steer, and approve the work.
- A successful repeatable method becomes a Play only when the human chooses to save it.
- The human may keep it private, share it with an authorized team, or publish it for the community.
- Credentials remain local and nothing runs before the exact inspected work is approved.

Do not use `adapter`, `crystallize`, `inference substrate`, `workflow artifact`, or other machinery
in the first-use explanation. Do not imply that raw conversation, credentials, or unchosen private
knowledge becomes memory.

## Typed choices

After the orientation is presented and remembered, offer:

1. **Run Hello** — use the pinned canonical URI
   `https://play.modiqo.ai/modiqo/hello@0.2.0`; disclose it, then run locally or request the exact
   remote pull approval.
2. **Tell me your goal** — accept ordinary language and route it through normal Play invocation.
3. **See useful Plays** — open the normal remembered awareness inbox.
4. **Not now** — finish without inspection or execution.

The starter choice selects the exact Play for read-only inspection. A proven local copy proceeds to
execution; a remote copy preserves the normal `approve_play_run` pull gate. Pin the exact starter
version; replacing it requires a deliberate source change and tests.

After a verified starter receipt, explain what happened without replacing or summarizing the full
result. Teach the reason for every stage:

1. **Inspect — see the X-ray.** Reveal the exact version, inputs, dependencies, operations, and
   declared effects before execution.
2. **Approve — set the boundary.** Bind consent to the inspected method, parameters, remote pull,
   and any declared writes; a changed method requires another decision.
3. **Run — execute the checked method.** Rote runs the exact inspected version locally and keeps
   local credentials local.
4. **Verify — prove the outcome.** Compare output with the requested result and retain a receipt;
   process completion alone is not success.

Show the equivalent outside-agent commands without `--yes`, so normal Rote approval remains intact:

```bash
rote play inspect modiqo/hello@0.2.0 --json
rote play run modiqo/hello@0.2.0
```

Then offer another Play by domain, creation from a useful outcome, a team space, or Finish. Explain
the creation boundary precisely: begin with `$play <do something useful>` so capture classification
happens before exploration; steer the work; after verification, ask to save the captured method.
Never suggest that uncaptured work can be converted into a Play retrospectively.

## Owner-private memory

Use `~/.rote/play/onboarding-state.json` only for first-use orientation memory. Store:

- a SHA-256 digest of the authenticated email;
- the orientation version;
- the UTC time when the orientation was presented.

Use user-only directory and file permissions. Store no email, request, prompt, Play result,
credential, raw `whoami` output, or controller context. Treat a missing entry as first use, the
current version as returning, and malformed state as a blocker. Record the marker only after the
presentation event succeeds. Keep first orientation and first verified Play activation separate.
