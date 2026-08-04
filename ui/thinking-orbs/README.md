# Play thinking-orbs adapter

This optional React adapter renders the current Play controller state with the corresponding
`thinking-orbs` animation and accessible status label.

```tsx
import { PlayThinkingOrb } from '@modiqo/play-thinking-orbs';

<PlayThinkingOrb playState="explore_execute" size={20} />
```

Pass only a validated `play.context/v1` current state. Do not derive `playState` from narrative text
or tool activity. Terminal states pause automatically; callers may explicitly set `paused` for a
host-level pause.

The source mapping is `../../references/integration/thinking-orbs.json`, and the full integration
contract is documented beside it in `thinking-orbs.md`.
