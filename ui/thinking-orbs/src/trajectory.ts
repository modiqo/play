import type { OrbState } from 'thinking-orbs';
import mapping from '../../../references/integration/thinking-orbs.json';

export type PlayState = keyof typeof mapping.states;

export interface PlayOrbPresentation {
  orb: OrbState;
  label: string;
  message: string;
  glyph: string;
  terminal: boolean;
}

type RawPresentation = {
  orb: OrbState;
  label: string;
  message?: string;
  terminal?: boolean;
};

const rawStates = mapping.states as Record<PlayState, RawPresentation>;
const trajectories = mapping.trajectories as Record<
  OrbState,
  { glyph: string; message: string }
>;

export const PLAY_ORB_PRESENTATIONS = Object.fromEntries(
  Object.entries(rawStates).map(([state, presentation]) => {
    const trajectory = trajectories[presentation.orb];
    return [
      state,
      {
        orb: presentation.orb,
        label: presentation.label,
        message: presentation.message ?? trajectory.message,
        glyph: trajectory.glyph,
        terminal: presentation.terminal ?? false
      }
    ];
  })
) as Record<PlayState, PlayOrbPresentation>;

export function presentationForPlayState(state: PlayState): PlayOrbPresentation {
  return PLAY_ORB_PRESENTATIONS[state];
}
