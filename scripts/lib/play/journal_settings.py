"""Owner-private settings for Play's automatic journals."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .private_store import atomic_write_json, load_json, locked_store
from .state_home import state_path


SCHEMA = "play.journal-settings/v1"
DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA,
    "enabled": True,
    "exploration": {
        "enabled": True,
        "interval_steps": 5,
        "min_interval_seconds": 120,
    },
    "recall": {
        "enabled": True,
        "retention_days": 30,
    },
}


def settings_path() -> Path:
    override = os.environ.get("PLAY_JOURNAL_SETTINGS_PATH")
    return Path(override) if override else state_path("journal-settings.json")


def _merge_defaults(value: object) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULTS)
    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        return merged
    if isinstance(value.get("enabled"), bool):
        merged["enabled"] = value["enabled"]
    for section in ("exploration", "recall"):
        configured = value.get(section)
        if not isinstance(configured, Mapping):
            continue
        for key in merged[section]:
            if key in configured and isinstance(configured[key], type(merged[section][key])):
                merged[section][key] = configured[key]
    return merged


def load_journal_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    try:
        value = load_json(target)
    except (OSError, ValueError):
        value = None
    return _merge_defaults(value)


def ensure_journal_settings(path: Path | None = None) -> tuple[dict[str, Any], bool]:
    """Create or migrate journal defaults without re-enabling an explicit opt-out."""

    target = path or settings_path()
    with locked_store(target.parent):
        try:
            existing = load_json(target)
        except (OSError, ValueError):
            existing = None
        settings = _merge_defaults(existing)
        changed = existing != settings
        if changed:
            atomic_write_json(target, settings)
    return settings, changed


def journal_enabled(kind: str, path: Path | None = None) -> bool:
    settings = load_journal_settings(path)
    section = settings.get(kind)
    return bool(
        settings.get("enabled")
        and isinstance(section, Mapping)
        and section.get("enabled")
    )


def positive_setting(kind: str, name: str, fallback: int, path: Path | None = None) -> int:
    settings = load_journal_settings(path)
    section = settings.get(kind)
    value = section.get(name) if isinstance(section, Mapping) else None
    return value if isinstance(value, int) and value > 0 else fallback
