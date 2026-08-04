# Thinking-orb host integration

Use the optional `ui/thinking-orbs` React adapter when a host exposes a custom activity surface.
The controller remains authoritative: render from the current `play.context/v1` machine state, not
from guessed prose, tool names, elapsed time, or implementation owner.

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

Skills cannot replace Codex, Claude Code, Cursor, or Kimi's native activity chrome. Hosts that do
not expose a React extension point should ignore this optional adapter and continue using Play's
milestone-only text updates.
