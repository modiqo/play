"""Portable digest windows and host-persistable checkpoint tokens."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CHECKPOINT_SCHEMA = "play.digest-checkpoint/v1"


class TimeWindowError(ValueError):
    pass


def parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise TimeWindowError(f"{field} is missing or invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise TimeWindowError(f"{field} is not an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise TimeWindowError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def load_checkpoint(path: Path) -> datetime:
    try:
        payload: Any = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise TimeWindowError(f"cannot load checkpoint: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema") != CHECKPOINT_SCHEMA:
        raise TimeWindowError(f"checkpoint must use {CHECKPOINT_SCHEMA}")
    return parse_timestamp(payload.get("last_seen_at"), field="checkpoint.last_seen_at")


def resolve_window(
    *,
    end: datetime,
    days: int,
    since: str | None = None,
    checkpoint: Path | None = None,
) -> tuple[datetime, datetime]:
    normalized_end = end.astimezone(timezone.utc)
    if since is not None and checkpoint is not None:
        raise TimeWindowError("--since and --checkpoint are mutually exclusive")
    if since is not None:
        start = parse_timestamp(since, field="--since")
    elif checkpoint is not None:
        start = load_checkpoint(checkpoint)
    else:
        start = normalized_end - timedelta(days=days)
    if start >= normalized_end:
        raise TimeWindowError("digest window start must be before its end")
    return start, normalized_end


def next_checkpoint(end: datetime) -> dict[str, str]:
    return {
        "schema": CHECKPOINT_SCHEMA,
        "last_seen_at": end.astimezone(timezone.utc).isoformat(),
    }
