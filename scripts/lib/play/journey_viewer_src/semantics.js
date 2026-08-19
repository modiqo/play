export const KIND_LABEL = {
  intent: 'Intent', decision: 'Decision', capability: 'Capability', authority: 'Authority',
  phase: 'Phase', effect: 'Effect', evidence: 'Evidence', artifact: 'Artifact',
  blocker: 'Blocker', recovery: 'Recovery', milestone: 'Milestone', learning: 'Learning',
  play_candidate: 'Play candidate', play: 'Play',
}

export const MAP_MEANING = {
  intent: 'Defines the outcome the agent is trying to reach.',
  decision: 'Records a choice between possible routes.',
  capability: 'Identifies the tool or service that can advance the work.',
  authority: 'Confirms permission before an external effect occurs.',
  phase: 'Groups several interactions serving one understandable purpose.',
  effect: 'Performs outcome-bearing work in an external system.',
  evidence: 'Checks what actually happened before accepting the result.',
  artifact: 'Packages the verified result into something usable.',
  blocker: 'Makes the condition that stopped progress visible.',
  recovery: 'Shows how the agent returned to a valid route.',
  milestone: 'Marks a meaningful achievement in the journey.',
  learning: 'Preserves knowledge discovered during the work.',
  play_candidate: 'Shapes verified work into a reusable procedure.',
  play: 'Makes the verified procedure available for future journeys.',
}

export const WORLD_ROLE = {
  intent: 'Starting gate',
  decision: 'Fork in the road',
  capability: 'Station',
  authority: 'Checkpoint',
  phase: 'Journey chamber',
  effect: 'Worksite',
  evidence: 'Observatory',
  artifact: 'Destination',
  blocker: 'Barricade',
  recovery: 'Bridge',
  milestone: 'Monument',
  learning: 'Knowledge marker',
  play_candidate: 'Reusable blueprint',
  play: 'Published gateway',
}

export const WORLD_STORY = {
  intent: 'The journey begins by fixing the destination before choosing a route.',
  decision: 'The agent pauses here because more than one valid route is available.',
  capability: 'The agent equips a tool or service here before it can act.',
  authority: 'The route cannot continue until the required permission is present.',
  phase: 'Several low-level interactions become one understandable stretch of the journey.',
  effect: 'This is where the agent touches the outside world to advance the outcome.',
  evidence: 'The agent looks back from here and checks whether the work really succeeded.',
  artifact: 'Verified work arrives here as something the user can keep or use.',
  blocker: 'Progress stopped here; the obstruction remains visible rather than being hidden.',
  recovery: 'A corrected route reconnects the agent to the intended journey.',
  milestone: 'The journey crosses a boundary worth remembering.',
  learning: 'Knowledge discovered on the route is preserved here.',
  play_candidate: 'A successful route is compressed here into a reusable blueprint.',
  play: 'The blueprint becomes a route that another journey can follow.',
}


