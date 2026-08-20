# Start Here narration

This script is the human-reviewed source for the Journey tutorial voice track. The synchronized, renderer-facing copy lives in `cues.json`.

Most interfaces anthropomorphize an agent from the outside, as if it were a person. We do the opposite. We embody the agent inside the situation where it operates, and let you experience its vantage point. The world begins with exact primitives and paraphrases them as a spatial narrative.

We turn an agent trace into a spatio-temporal experience as an homage to Doom, Wolfenstein 3D, and Halo: games that taught us a world through movement, landmarks, and time. We borrow that legibility, not their visual style.

Begin at the gate. Our example intent is: create a page in Notion and verify it. Intent fixes that destination before the agent chooses a route.

At the fork, the agent chooses among Notion MCP through CALL, notion-cli through SHELL, and the Notion website through DRIVE. This mixed-modality tutorial uses all three so their responsibilities remain visible.

A station is an equipped capability instance. The first station initializes the Notion adapter through CALL. The station exists before its operations and persists across them.

The checkpoint is authority. When access is required, the route cannot honestly continue until it is satisfied.

The first worksite queries the target Notion database. The effect is an operation performed through the capability, distinct from the station that enabled it.

The first page-creation attempt reaches a barricade because the parent database is not shared. Once access is corrected, a bridge preserves the successful retry as recovery rather than erasing the failure.

A second station equips notion-cli through SHELL for local validation. A third equips a browser lease through DRIVE to open the created page and verify it from the outside.

Recorded operations become floating glass beads on a frontage timeline. Landmarks are places; beads are events. Read left to right from past to present. Horizontal gaps show elapsed time, bead volume shows token volume, halo sweep shows operation duration, and depth shows proven overlap.

The browser station equips DRIVE: a leased page session with its own evidence ledger.

Browser actions and observations remain operations. Their beads do not become capabilities merely because they use one.

At the destination, verified evidence becomes an artifact the user can keep or use.

## Production contract

- Voice: synthesize this approved script through the installed ElevenLabs Rote adapter.
- Music: use a licensed instrumental bed with no speech and preserve its source/license receipt.
- Mix: voice remains intelligible; music ducks beneath speech; export normalized browser-safe audio.
- Provenance: record adapter operation, voice/model identifiers, input-script SHA-256, music license/source, output SHA-256, and review status in `provenance.json`.
- Safety: generated media is optional. The tutorial must remain complete through captions and deterministic recorded evidence when audio is absent.
