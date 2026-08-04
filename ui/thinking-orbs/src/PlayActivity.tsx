import type { CSSProperties, HTMLAttributes } from 'react';
import type { ThinkingOrbProps } from 'thinking-orbs';
import { PlayThinkingOrb } from './PlayThinkingOrb';
import { presentationForPlayState, type PlayState } from './trajectory';

export interface PlayActivityProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  playState: PlayState;
  message?: string;
  orbProps?: Omit<ThinkingOrbProps, 'state' | 'aria-label'>;
  messageStyle?: CSSProperties;
}

export function PlayActivity({
  playState,
  message,
  orbProps,
  messageStyle,
  style,
  ...containerProps
}: PlayActivityProps) {
  const presentation = presentationForPlayState(playState);

  return (
    <div
      {...containerProps}
      role="status"
      aria-live="polite"
      aria-label={presentation.label}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 8, ...style }}
    >
      <PlayThinkingOrb
        {...orbProps}
        playState={playState}
        size={orbProps?.size ?? 20}
        aria-hidden="true"
      />
      <span aria-hidden="true" style={messageStyle}>
        {message ?? presentation.message}
      </span>
    </div>
  );
}
