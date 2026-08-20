# Journey World Model v2

- **Status:** Reference design; implementation in progress
- **Owners:** Play owns semantic projection and presentation; Rote owns execution evidence
- **Applies to:** `play-journey view --active`, recorded Journey replay, and tutorial replay
- **Compatibility:** Existing Rote workspaces and `play.journey-graph/v1` recordings remain replayable
- **Projection target:** Additive `play.journey-graph/v1` fields under a new projection rules version

## Decision

Journey will represent four orthogonal ideas instead of flattening them into one node kind:

1. **Semantic role** tells the user why a place exists.
2. **Modality** tells the user how the agent can act there.
3. **Capability lifecycle** tells the user whether the system is equipped and authorized.
4. **Operations** are the time-ordered actions performed through that capability.

The visual grammar follows the same separation:

| Meaning | Visual channel |
|---|---|
| Semantic role | Landmark shape |
| Modality | A consistent treatment applied to capability stations and operation markers |
| Lifecycle state | Construction, illumination, checkpoint, and state marks |
| Operation chronology | A local left-to-right time axis at the current vantage |
| Journey chronology | The global amber route and replay progress |
| Outcome/effect posture | Read/write/mixed/unknown marks and outcome landmarks |

The same capability station remains recognizable across modalities. CALL/adapter, SHELL/proc,
and DRIVE/browser modify the station's details; they do not replace the common capability shape.

## Canonical terminology

Rote's human-facing exploration modalities are CALL, SHELL, and DRIVE. Persisted command evidence
uses substrate-oriented capability families. Journey carries both without inventing a fourth
modality:

| Rote modality | Capability family | Interface | Examples |
|---|---|---|---|
| `call` | `adapter` | `api` | Notion, GitHub, ElevenLabs, data adapters |
| `shell` | `proc` | `shell` | `git`, `rg`, `pytest`, background leases |
| `drive` | `browser` | `browse` | page lease, navigation, snapshot, lens, action |

Rote-internal commands such as stored-response queries are supporting operations. They retain a
`family: rote` descriptor for audit but do not become a fourth equipped modality.

## Conceptual model

```text
Journey
  ├── semantic sites / vantages
  │     ├── intent, decision, authority, phase
  │     ├── capability, effect, evidence, artifact
  │     └── blocker, recovery, milestone, learning, play
  ├── capability instances
  │     ├── modality: call | shell | drive
  │     ├── family: adapter | proc | browser
  │     ├── identity: adapter:notion | proc:git | browser:page-session
  │     ├── lifecycle observations
  │     └── authorization state
  └── operations
        ├── canonical Rote sequence and timestamp
        ├── capability reference
        ├── semantic role and effect posture
        ├── request/response evidence references
        └── duration, token, status, and dependency evidence
```

A vantage is a semantic site at which the camera can stop. A command is not automatically a
vantage. Supporting operations can remain inside the local time series of an existing site, while
material lifecycle or outcome changes create a new site.

## Capability contract

Every adapter, executable, or browser session used by the journey resolves to a stable capability
instance. The projection must never infer identity from arbitrary argument text.

```json
{
  "schema": "play.journey-capability-instance/v1",
  "id": "cap_adapter_notion",
  "modality": "call",
  "family": "adapter",
  "interface": "api",
  "subject": "notion",
  "label": "Notion",
  "initialization": {
    "state": "ready",
    "basis": "observed_probe",
    "first_sequence": 1
  },
  "authorization": {
    "state": "satisfied",
    "required": true,
    "basis": "typed_authority_event"
  },
  "operation_sequences": [3, 4, 5]
}
```

### Lifecycle vocabulary

```text
discovered
initializing
initialized
authorization_required
authorized
ready
active
closed
failed
```

The graph stores observations, not a fictional perfect lifecycle. When first use is the earliest
available evidence, Journey may synthesize a capability station with `basis: observed_use`; it may
not claim that a probe, login, or explicit initialization occurred.

Authorization has its own closed state:

```text
not_applicable
unknown
required
satisfied
failed
```

Access to a capability does not imply authority to perform an effect. Adapter authentication,
browser session availability, and effect approval remain distinct evidence.

## Operation contract

The normalized activity record remains the canonical operation projection. It gains stable
ownership fields:

```json
{
  "sequence": 14,
  "capability_ref": "cap_adapter_notion",
  "modality": "call",
  "lifecycle_phase": "use",
  "semantic_kind": "effect",
  "effect_profile": {
    "posture": "write",
    "scopes": ["external_service"],
    "source": "adapter_tool_contract",
    "confidence": "deterministic",
    "destructive": false
  }
}
```

Classification occurs in this order:

1. Decode the typed Rote command.
2. Resolve capability family and identity.
3. Map family to modality.
4. Classify effect posture from typed contracts and receipts.
5. Classify lifecycle phase: initialize, authorize, use, observe, or close.
6. Classify semantic role.
7. Apply failure/recovery overlays.
8. Group supporting operations without deleting their canonical records.

Operation names and free-text arguments are display copy only. They cannot manufacture safety,
authority, or capability identity.

## Primitive classification

| Rote primitive | Lifecycle phase | Default semantic role |
|---|---|---|
| `InitSession` | `initialize` | `capability` |
| Adapter probe/protocol request | `initialize` | `capability` |
| Browser lease/session initialization | `initialize` | `capability` |
| `adapter.auth.ensure` | `authorize` | `authority` |
| Adapter/browser operation | `use` | `effect` with typed posture |
| `DataQuery` | `use` | read `effect` |
| `For` | `use` | external `effect`; never generic phase |
| `DepsCheck` | `initialize` | `capability` |
| Read-only proc operation | `use` | inspection `phase` |
| Write/mixed proc operation | `use` | `effect` |
| Proc interactive authentication | `authorize` | `authority` |
| Background status/wait | `observe` | supporting `phase` |
| Background stop | `close` | process `effect` or explicit unknown effect |
| `StreamFollow` | `observe` | supporting `evidence` |
| `QueryRead`, `QueryExtract`, `Display` | `observe` | supporting `evidence` |
| `Inject` | `initialize` | evidence/capability input, not generic phase |
| `SetVariable` | `use` | local `decision` |
| `ComposeEmail` | `use` | `artifact` |

Any failed activity becomes a blocker. A later successful activity with the same deterministic
signature becomes a recovery. The operation retains its original modality and capability owner.

## Graph projection

The graph adds a top-level `capabilities` collection and operation ownership fields. Existing node
kinds and evidence links remain valid. Capability nodes gain `capability_ref`; operation-bearing
nodes gain the distinct capability references used within the site.

New edge semantics are additive:

```text
initializes      intent/decision → capability
requires         capability → authority
authorizes       authority → capability or effect
uses             operation-bearing site → capability
executes         capability → effect
observes         capability/effect → evidence
```

If the existing v1 edge vocabulary cannot express the distinction without ambiguity, the graph
schema advances to v2. Until then, `requires`, `authorizes`, `executes`, and `derived_from` remain
the compatibility projection while explicit references carry exact ownership.

### Replay and migration

- Rote workspaces remain authoritative and require no migration.
- A projection-rule bump rebuilds Journey graphs from the same Rote evidence.
- Existing graph snapshots without capability instances receive conservative compatibility
  instances derived from their persisted capability descriptors.
- Compatibility instances use `basis: legacy_projection` and never claim authorization.
- Exports retain canonical Rote command sequences and response references.
- Tutorial data is marked and cannot be mistaken for owner work.

## Spatial vocabulary

### Landmark registry

One shared registry owns label, world role, story, glyph, and 3D landmark family. The legend and
renderer may no longer define the same vocabulary independently.

All supported semantic kinds must be either represented or explicitly marked as supporting-only.
The initial complete vocabulary includes decision, phase, learning, and play, which the current
legend omits.

### Capability stations

All capability instances use the station silhouette. Modality adds a secondary treatment:

- CALL/adapter: service manifold, connection ports, or API terminal blocks.
- SHELL/proc: terminal aperture, rails, and process status light.
- DRIVE/browser: viewport frame, lens, and page-lease marker.

Lifecycle changes the station state:

- discovered: outline only;
- initializing: staged construction/pulse;
- authorization required: checkpoint closed;
- ready: complete, steady illumination;
- active: operation conduit illuminated;
- failed: interrupted conduit and blocker treatment;
- closed: dim but preserved for history.

### Operation structures

Operations remain lossless glass structures with modality marks and explicit capability ownership.
Shape does not need to encode every operation name. The local time axis, label, posture, and
capability tether provide that information.

## Temporal grammar

Journey presents two related time scales:

1. **Global journey time:** progress between semantic vantages.
2. **Local operation time:** the ordered Rote interactions within a vantage.

The existing temporal corridor already computes chronology, bounded logarithmic gaps, concurrency
lanes, deltas, a spine, and entrance/exit points. The renderer must expose those results.

At a frozen vantage it renders:

- a visible PAST → PRESENT spine;
- an `@N` tick for every canonical operation;
- elapsed-time labels and meaningful gap markers;
- duration footprints;
- deeper lanes only for proven overlap;
- a moving playhead during replay;
- modality and effect-posture marks;
- lossless aggregation at distance and expansion on inspection.

Visual variables have one meaning each:

| Variable | Meaning |
|---|---|
| X position | operation start time/order |
| Base width | duration |
| Depth lane | proven concurrency |
| Height | token volume |
| Modality mark/material detail | CALL, SHELL, DRIVE |
| Posture mark | read, write, mixed, unknown |
| Fracture/barricade | failure/blocker |

Latency is represented once by the duration footprint. Token volume is represented once by height;
the two signals are never blended into a composite score.

## Start Here tutorial workspace

Journey ships a deterministic, resettable recorded workspace that teaches the world through the
same projection and renderer used for owner work.

Before replay, a bionic-emphasis reading card establishes the thesis: Journey does not
anthropomorphize an agent from the outside; it embodies the viewer at the agent's vantage inside
the situation where it operates. The card states the exact primitives in plain English and then
shows how the spatial narrative paraphrases them. Replay begins only after this orientation, and
completion ends with a direct `Choose a workspace` handoff.

On a first launch with no explicit `?workspace=...` deep link, the viewer selects Start Here even
when a live capture exists. An explicit workspace URL and an in-session user selection always win
over that default.

The experience turns an agent trace into a spatio-temporal world as an homage to Doom,
Wolfenstein 3D, and Halo: games that made their worlds legible through movement, landmarks, and
time. This is a design lineage, not an imitation of their visual assets or trade dress.

The tutorial route demonstrates:

1. intent;
2. CALL capability initialization;
3. authorization;
4. read and write adapter operations;
5. SHELL initialization and operations;
6. DRIVE initialization and operations;
7. evidence verification;
8. blocker and recovery;
9. artifact delivery.

One continuous example carries the learner through the reference and replay: create a page in
Notion, decide among Notion MCP/CALL, notion-cli/SHELL, and browser/DRIVE, then use all three to
prepare, create, observe, verify, and deliver the page. Every world-model entry includes a small
example drawn from that thread for readers who reason more easily from concrete cases.

At each tutorial stop, surrounding landmarks and labels dim and soften while the current landmark
retains its original glass/material treatment, lifts slightly, and receives only a restrained amber
edge. Focus must never repaint the primitive as a solid orange object. The World Model reference
opens at tutorial entry and remains one click away throughout the replay, with its current primitive
highlighted.

Tutorial entry is a serialized reveal, never overlapping glass panels: the world first dims behind
the World Model while its primitive rows resolve in order; continuing closes that structure and
reveals the manifesto/orientation card; entering the card begins the embodied replay.

A compact, dismissible glass caption names the shape, maps it back to the exact world-model
primitive, and explains why the local operation towers sit in front of this vantage: they are
inspectable evidence belonging to this semantic step, not additional stops on the global route.
The caption clears during travel so it does not become permanent HUD obstruction. It repeats the
tower channels and tells the learner to pause and select an amber tower or `@sequence` plaque to
inspect its redacted exchange.

It is identified by a typed tutorial origin and is visually labeled `START HERE`. It is never
included in capture counts, publication, crystallization, or owner-history claims.

The first implementation is a recorded replay because it is deterministic and available without
credentials. A later `WATCH LIVE` option attaches the same traveler and vocabulary to the current
workspace.

## Narration and music

Narration is an optional presentation layer, not semantic evidence and not a runtime dependency on
an external provider.

The repository stores:

```text
scripts/lib/play/journey_tutorial/
  narration.md
  cues.json
  provenance.json
  narration.mp3       # optional reviewed production asset
  music.mp3           # optional original or licensed production asset
```

Cues bind to chapter IDs and optional operation sequences rather than absolute playback position.
The viewer offers captions, mute, independent voice/music volume, and free exploration. The
ElevenLabs adapter is used only by an explicit production command that records model, voice,
settings, content digest, and resulting asset digest. Missing credentials never affect Journey.

## Implementation order

1. Add and test the semantic contract, capability identity, lifecycle, and primitive matrix.
2. Project capability instances and operation ownership; rebuild old workspaces by rule version.
3. Replace independent legend/landmark definitions with a shared vocabulary registry.
4. Render global and local time axes with unambiguous visual variables.
5. Materialize and expose the deterministic Start Here tutorial workspace.
6. Add narration script, cue schema, audio controls, and explicit asset-production command.
7. Verify replay, export, packaging, privacy, accessibility, and performance.

## Acceptance criteria

- Every adapter/proc/browser operation references exactly one capability instance.
- Every capability declares modality, identity, lifecycle basis, and authorization state.
- CALL, SHELL, and DRIVE are visually distinguishable without changing the station's base shape.
- Direct first use creates an honest `observed_use` station rather than inventing initialization.
- `For`, `Inject`, adapter protocol, and background process lifecycle have explicit classifications.
- Failure and recovery preserve capability ownership.
- Every rendered legend glyph corresponds to its actual 3D landmark family.
- Decision, phase, learning, and play are no longer silent fallback shapes.
- Frozen vantages visibly communicate chronology, gaps, duration, concurrency, and posture.
- Existing owner workspaces replay after a projection-rule rebuild without raw-evidence changes.
- Start Here is clearly tutorial data, resettable, and excluded from owner claims.
- Audio is optional, captioned, provenance-bound, and never required to operate the viewer.
