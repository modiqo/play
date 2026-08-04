# Thinking-orb host integration

Use the optional `ui/thinking-orbs` React adapter when a host exposes a custom activity surface.
The controller remains authoritative: render from the current `play.context/v1` machine state, not
from guessed prose, tool names, elapsed time, or implementation owner.

Every trajectory also defines a short playful message and a static orb-like glyph. Resolve the
portable contract with:

```bash
scripts/bin/play-presentation use_run --json
scripts/bin/play-presentation use_run
```

The JSON form is `play.presentation/v1` and is intended for a host renderer. The plain form is the
truthful terminal/chat fallback, for example `⟡ Wiring the right pieces together…`. It is not an
animation. Agents should use either the host-rendered event or the fallback line for a milestone,
never both.

The exhaustive mapping lives in `thinking-orbs.json` and uses all nine animations by trajectory:

| Orb | Play trajectory |
|---|---|
| `listening` | A declared prompt is waiting for consent, input, or a selection |
| `searching` | Local/registry discovery, awareness collection, or inventory loading |
| `solving` | Qualification, adequacy classification, routing, or outcome verification |
| `connecting` | Inspecting dependencies, running an existing Play, resolving ownership, or readback |
| `weaving` | Preparing or coordinating multimodal Explore work |
| `shaping` | Crystallizing verified evidence into a reusable candidate |
| `composing` | Authoring a release or publishing it privately/publicly |
| `working` | Presenting results, assembling a receipt, or indexing |
| `breathing` | A settled terminal state; render it paused so it does not imply continuing work |

Use `size={64}` for a primary assistant/avatar surface and `size={20}` beside an inline status.
Keep `theme="auto"` unless the host cannot expose its theme convention. Preserve the mapping's
specific `aria-label`; the visual state alone is not a sufficient status announcement.

Do not mount an orb before Play has a valid context, and unmount it when the host dismisses the
activity surface. Terminal states are deliberately paused. A blocked state must also retain its
textual blocker and recovery path; the neutral monochrome orb is not an error indicator.

Render only user-visible milestones. Do not turn all controller transitions into status chatter.
Prompt-state messages belong beside the declared question; terminal messages belong inside the
outcome. While `rote play run` is executing, Rote owns its own terminal progress and Play must not
claim that the React orb is visible unless the host actually mounted the renderer.

Skills cannot replace Codex, Claude Code, Cursor, or Kimi's native activity chrome. Hosts that do
not expose a React extension point should ignore this optional adapter and continue using Play's
milestone-only text updates.
