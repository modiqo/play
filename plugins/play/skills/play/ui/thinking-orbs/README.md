# Play thinking-orbs adapter

This optional React adapter renders the current Play controller state with the corresponding
`thinking-orbs` animation and accessible status label.

```tsx
import { PlayActivity } from '@modiqo/play-thinking-orbs';

<PlayActivity playState="explore_execute" />
```

Pass only a validated `play.context/v1` current state. Do not derive `playState` from narrative text
or tool activity. Terminal states pause automatically; callers may explicitly set `paused` for a
host-level pause.

`PlayActivity` renders the 20px orb with the trajectory's playful message. Use `PlayThinkingOrb`
directly when the host already owns its status-copy layout.

The source mapping is `../../references/integration/thinking-orbs.json`, and the full integration
contract is documented beside it in `thinking-orbs.md`.
