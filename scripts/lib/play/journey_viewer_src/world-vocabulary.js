export const WORLD_VOCABULARY = Object.freeze({
  intent: {
    label: 'Intent', role: 'Starting gate', landmark: 'gate', glyph: 'gate',
    meaning: 'Defines the outcome the agent is trying to reach.',
    story: 'The journey begins by fixing the destination before choosing a route.',
  },
  decision: {
    label: 'Decision', role: 'Fork in the road', landmark: 'fork', glyph: 'fork',
    meaning: 'Records a choice between possible routes.',
    story: 'The agent pauses here because more than one valid route is available.',
  },
  capability: {
    label: 'Capability', role: 'Station', landmark: 'station', glyph: 'station',
    meaning: 'Represents an equipped and initialized system through which operations run.',
    story: 'The agent equips and initializes an adapter, shell, or browser capability here.',
  },
  authority: {
    label: 'Authority', role: 'Checkpoint', landmark: 'checkpoint', glyph: 'checkpoint',
    meaning: 'Confirms authentication, permission, or approval before an effect.',
    story: 'The route cannot continue until the required authority is satisfied.',
  },
  phase: {
    label: 'Phase', role: 'Journey chamber', landmark: 'chamber', glyph: 'chamber',
    meaning: 'Groups several supporting operations serving one purpose.',
    story: 'Low-level interactions become one understandable stretch of the journey.',
  },
  effect: {
    label: 'Effect', role: 'Worksite', landmark: 'crater', glyph: 'crater',
    meaning: 'Performs outcome-bearing work in an external or privileged system.',
    story: 'This is where an equipped capability changes or retrieves the outside world.',
  },
  evidence: {
    label: 'Evidence', role: 'Observatory', landmark: 'observatory', glyph: 'observatory',
    meaning: 'Checks what actually happened before accepting the result.',
    story: 'The agent looks back from here and checks whether the work really succeeded.',
  },
  artifact: {
    label: 'Artifact', role: 'Destination', landmark: 'destination', glyph: 'destination',
    meaning: 'Packages verified work into something the user can keep or use.',
    story: 'Verified work arrives here as a durable result.',
  },
  blocker: {
    label: 'Blocker', role: 'Barricade', landmark: 'barricade', glyph: 'barricade',
    meaning: 'Makes the condition that stopped progress visible.',
    story: 'Progress stopped here; the obstruction remains visible rather than being hidden.',
  },
  recovery: {
    label: 'Recovery', role: 'Bridge', landmark: 'bridge', glyph: 'bridge',
    meaning: 'Shows how the agent returned to a valid route.',
    story: 'A corrected route reconnects the agent to the intended journey.',
  },
  milestone: {
    label: 'Milestone', role: 'Monument', landmark: 'monument', glyph: 'monument',
    meaning: 'Marks a meaningful achievement in the journey.',
    story: 'The journey crosses a boundary worth remembering.',
  },
  learning: {
    label: 'Learning', role: 'Knowledge marker', landmark: 'archive', glyph: 'archive',
    meaning: 'Preserves knowledge discovered during the work.',
    story: 'A durable insight is stored here for later journeys.',
  },
  play_candidate: {
    label: 'Play candidate', role: 'Reusable blueprint', landmark: 'blueprint', glyph: 'blueprint',
    meaning: 'Shapes verified work into a reusable procedure.',
    story: 'A successful route is compressed here into a reusable blueprint.',
  },
  play: {
    label: 'Play', role: 'Published gateway', landmark: 'gateway', glyph: 'gateway',
    meaning: 'Makes the verified procedure available for future journeys.',
    story: 'The blueprint becomes a gateway another journey can follow.',
  },
})

export const WORLD_MODEL_KINDS = Object.freeze(Object.keys(WORLD_VOCABULARY))

export const MODALITY_VOCABULARY = Object.freeze({
  call: {label: 'CALL · ADAPTER', note: 'Typed API or data capability', mark: 'ports'},
  shell: {label: 'SHELL · PROC', note: 'CLI, PTY, process, or stream capability', mark: 'terminal'},
  drive: {label: 'DRIVE · BROWSER', note: 'Leased browser session capability', mark: 'viewport'},
})

export function worldSpec(kind) {
  return WORLD_VOCABULARY[kind] || WORLD_VOCABULARY.phase
}

export const KIND_LABEL = Object.fromEntries(Object.entries(WORLD_VOCABULARY).map(([kind, value]) => [kind, value.label]))
export const MAP_MEANING = Object.fromEntries(Object.entries(WORLD_VOCABULARY).map(([kind, value]) => [kind, value.meaning]))
export const WORLD_ROLE = Object.fromEntries(Object.entries(WORLD_VOCABULARY).map(([kind, value]) => [kind, value.role]))
export const WORLD_STORY = Object.fromEntries(Object.entries(WORLD_VOCABULARY).map(([kind, value]) => [kind, value.story]))
