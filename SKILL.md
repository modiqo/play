---
name: play
description: >
  Run or create a reusable Play for an outcome. Use only when the user explicitly invokes Play
  (`/play` or `$play`). Play runs on rote: the request goes to `rote journey next`.
---

# Play

Play is a journey pack for rote. rote decides every step; this skill only hands the request over.

## Hand the request to rote

1. Run `rote guidance root` once per session and follow it. It is the protocol: what each yield
   means, how to ask, and how to resume.
2. Start the journey with the user's words unchanged, prefix included:

   ```sh
   rote journey next --json --harness <claude-code|codex|cursor|generic> "<request>"
   ```

3. Do what the one yield says, then run the resume command it gives. Repeat until a yield ends the
   session.

Do not search, inspect, run, save, or publish Plays yourself. The journey does each of these, and
asks the user where it needs an answer.

## Schedule a Play

Offer a schedule only after the journey presented a successful run, or when the user asks for
one. Schedule the exact versioned reference that run used:

```sh
play recurring schedule --reference <owner/name@x.y.z> --cadence "<cadence>" --why "<reason>"
```

`play recurring --help` lists the other scheduling commands.

## When rote is missing

If `rote` is not on `PATH`, check `$ROTE_BIN/rote`, then `$HOME/.local/bin/rote`. If neither
exists, tell the user to install rote with the Play pack, and do not run it without their approval:

```sh
curl -fsSL https://getrote.dev/install | bash -s -- --pack play
```
