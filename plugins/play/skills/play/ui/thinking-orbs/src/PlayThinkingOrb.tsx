import { ThinkingOrb, type ThinkingOrbProps } from 'thinking-orbs';
import { presentationForPlayState, type PlayState } from './trajectory';

export interface PlayThinkingOrbProps
  extends Omit<ThinkingOrbProps, 'state' | 'aria-label'> {
  playState: PlayState;
  'aria-label'?: string;
}

export function PlayThinkingOrb({
  playState,
  paused,
  'aria-label': ariaLabel,
  ...orbProps
}: PlayThinkingOrbProps) {
  const presentation = presentationForPlayState(playState);

  return (
    <ThinkingOrb
      {...orbProps}
      state={presentation.orb}
      paused={paused ?? presentation.terminal}
      aria-label={ariaLabel ?? presentation.label}
    />
  );
}
