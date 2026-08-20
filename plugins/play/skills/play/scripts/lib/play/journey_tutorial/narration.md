# Start Here narration

This script is the human-reviewed source for the Journey tutorial voice track. The synchronized, renderer-facing copy lives in `cues.json`.

Most interfaces anthropomorphize an agent from the outside, as if it were a person. We do the opposite. We embody the agent inside the situation where it operates, and let you experience its vantage point. The world begins with exact primitives and paraphrases them as a spatial narrative.

We turn an agent trace into a spatio-temporal experience as an homage to Doom, Wolfenstein 3D, and Halo: games that taught us a world through movement, landmarks, and time. We borrow that legibility, not their visual style.

Begin at the gate. Intent fixes the destination before the agent chooses a route.

A station is an equipped capability instance. This one uses CALL, the adapter modality. The station exists before its operations and persists across them.

The checkpoint is authority. When access is required, the route cannot honestly continue until it is satisfied.

The worksite is an operation performed through that capability. The effect is distinct from the station that enabled it.

A second station equips SHELL, Rote's proc modality, for local command execution.

Recorded operations form a frontage timeline. Read left to right from past to present. Horizontal gaps show elapsed time, footprint shows operation duration, height shows token volume, and depth shows proven overlap.

The browser station equips DRIVE: a leased page session with its own evidence ledger.

Browser actions and observations remain operations. Their towers do not become capabilities merely because they use one.

At the destination, verified evidence becomes an artifact the user can keep or use.

## Production contract

- Voice: synthesize this approved script through the installed ElevenLabs Rote adapter.
- Music: use a licensed instrumental bed with no speech and preserve its source/license receipt.
- Mix: voice remains intelligible; music ducks beneath speech; export normalized browser-safe audio.
- Provenance: record adapter operation, voice/model identifiers, input-script SHA-256, music license/source, output SHA-256, and review status in `provenance.json`.
- Safety: generated media is optional. The tutorial must remain complete through captions and deterministic recorded evidence when audio is absent.
