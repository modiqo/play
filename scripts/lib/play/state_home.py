"""Play's owner-private state home, deliberately independent of ``~/.rote``.

Play once stored its runtime state under ``~/.rote/play``. That coupled Play's
continuity to Rote's lifecycle: a setup flow that legitimately backs up or
relocates ``~/.rote`` silently took Play's live continuations, ledger, and
caches with it. Play state now lives under ``~/.rote-play`` — a sibling of ``~/.rote``, never
inside it — and any state still found at the legacy location is migrated
lazily on first access.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


LEGACY_HOME = Path.home() / ".rote" / "play"


def state_home() -> Path:
    override = os.environ.get("PLAY_STATE_HOME")
    return Path(override) if override else Path.home() / ".rote-play"


def state_path(name: str) -> Path:
    """Resolve one state file or directory, migrating legacy state on first use."""

    current = state_home() / name
    if current.exists():
        return current
    legacy = LEGACY_HOME / name
    if legacy.exists():
        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(current))
        except OSError:
            return legacy
    return current
