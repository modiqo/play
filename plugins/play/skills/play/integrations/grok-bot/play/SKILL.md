---
name: play
description: Route explicit `/play` and `play ...` requests from Grok Bot to the canonical Play installation on the user's registered computer.
---

# Play on Grok Bot

This is a transport pointer. The canonical Play recipe, runtime, Rote identity, credentials, and owner-private state stay on the user's registered computer.

## Execution boundary

For every `/play` or `play ...` request:

1. Use the user's registered computer, not the hosted Grok Bot machine.
2. On that computer, read `$HOME/.local/share/modiqo/play/skill/SKILL.md` completely before continuing.
3. Follow that canonical recipe for the request.
4. Run `$HOME/.local/bin/play-machine` and bundled Play scripts on the registered computer. When a helper requires a harness identifier, pass `--harness cursor` until Play defines a native Grok harness identifier.

If the registered computer is unavailable, or the canonical recipe or launcher is missing there, stop and explain the missing prerequisite. Never run a substitute Play runtime in the hosted agent box.

## Isolation

Do not copy Play's `.venv`, Rote installation, credentials, tokens, private state, caches, or model assets into Grok Bot's hosted machine. Return only the user-facing result and the minimum evidence required by the canonical Play recipe.
