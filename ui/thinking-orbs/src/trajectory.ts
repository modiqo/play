import type { OrbState } from 'thinking-orbs';
import mapping from '../../../references/integration/thinking-orbs.json';

export type PlayState = keyof typeof mapping.states;

export interface PlayOrbPresentation {
  orb: OrbState;
  label: string;
  terminal: boolean;
}

type RawPresentation = {
  orb: OrbState;
  label: string;
  terminal?: boolean;
};

const rawStates = mapping.states as Record<PlayState, RawPresentation>;

export const PLAY_ORB_PRESENTATIONS = Object.fromEntries(
  Object.entries(rawStates).map(([state, presentation]) => [
    state,
    {
      orb: presentation.orb,
      label: presentation.label,
      terminal: presentation.terminal ?? false
    }
  ])
) as Record<PlayState, PlayOrbPresentation>;

export function presentationForPlayState(state: PlayState): PlayOrbPresentation {
  return PLAY_ORB_PRESENTATIONS[state];
}
