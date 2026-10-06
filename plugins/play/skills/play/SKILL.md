---
name: play
description: >
  Sidekick for reusable procedures. Use only when the user explicitly invokes Play. Play runs and
  creates reusable procedures and manages its cheat sheet, onboarding, canonical Play URIs, digest,
  routing policy, management, sharing, and birth certificates.
---

# Play

This marketplace plugin is a pointer. Play is installed and updated through rote, which links the
real Play skill into this agent.

## Load the installed Play skill

If `${ROTE_HOME:-$HOME/.rote}/play/current/SKILL.md` exists, read it completely and follow it for
this request. It is the Play skill; resolve the bundled paths it names, such as `scripts/bin/...`,
against `${ROTE_HOME:-$HOME/.rote}/play/current`.

## When Play is not installed

If that file is missing, tell the user Play runs through rote and give them the install command:

- When `rote` is not on `PATH`: `curl -fsSL https://getrote.dev/install | bash`, which installs rote
  and then Play.
- Otherwise: `rote install play`.

Tell them to restart the agent afterwards so it loads the installed skill. Never run either command
without the user's approval. Never copy Play's runtime files, rote's installation, credentials, or
tokens into this plugin or the agent's skill directories.
