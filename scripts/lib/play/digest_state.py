"""Local, scope-keyed memory for explicitly requested Play digests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .registry import Organization
from .timewindow import CHECKPOINT_SCHEMA, parse_timestamp


STATE_SCHEMA = "play.digest-state/v1"
DEFAULT_STATE_PATH = Path.home() / ".rote" / "play" / "digest-state.json"


class DigestStateError(ValueError):
    """Remembered digest state is missing, malformed, or cannot be stored."""


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_sha(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def scope_contract(
    organizations: list[Organization],
    *,
    window_days: int,
    public_limit: int,
    inspection_budget: int,
    update_metadata_budget: int,
    update_inspection_budget: int,
) -> dict[str, Any]:
    """Describe the authorization-sensitive inputs that make one memory stream."""

    return {
        "organizations": sorted(org.slug for org in organizations),
        "window_days": window_days,
        "public_limit": public_limit,
        "inspection_budget": inspection_budget,
        "update_metadata_budget": update_metadata_budget,
        "update_inspection_budget": update_inspection_budget,
    }


def scope_key(scope: dict[str, Any]) -> str:
    return "scope_" + stable_sha(scope)[:24]


def _empty_state() -> dict[str, Any]:
    return {"schema": STATE_SCHEMA, "scopes": {}}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise DigestStateError(f"cannot load digest state: {error}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != STATE_SCHEMA
        or not isinstance(payload.get("scopes"), dict)
    ):
        raise DigestStateError(f"digest state must use {STATE_SCHEMA}")
    return payload


def load_entry(path: Path, key: str) -> dict[str, Any] | None:
    entry = load_state(path)["scopes"].get(key)
    if entry is None:
        return None
    checkpoint = entry.get("checkpoint") if isinstance(entry, dict) else None
    if (
        not isinstance(entry, dict)
        or not isinstance(entry.get("scope"), dict)
        or not isinstance(entry.get("awareness_sha"), str)
        or not isinstance(checkpoint, dict)
        or checkpoint.get("schema") != CHECKPOINT_SCHEMA
    ):
        raise DigestStateError(f"digest state entry {key} is malformed")
    parse_timestamp(checkpoint.get("last_seen_at"), field=f"digest state {key}.last_seen_at")
    return entry


def compare_digest(digest: dict[str, Any], previous: dict[str, Any] | None) -> str:
    current_sha = digest.get("awareness_sha")
    if not isinstance(current_sha, str) or not current_sha:
        raise DigestStateError("digest is missing awareness_sha")
    if previous is None:
        return "initial"
    return "unchanged" if previous["awareness_sha"] == current_sha else "changed"


def save_entry(
    path: Path,
    *,
    key: str,
    scope: dict[str, Any],
    digest: dict[str, Any],
) -> None:
    checkpoint = digest.get("next_checkpoint")
    awareness_sha = digest.get("awareness_sha")
    if not isinstance(checkpoint, dict) or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise DigestStateError(f"digest checkpoint must use {CHECKPOINT_SCHEMA}")
    if not isinstance(awareness_sha, str) or not awareness_sha:
        raise DigestStateError("digest is missing awareness_sha")

    state = load_state(path)
    state["scopes"][key] = {
        "scope": scope,
        "awareness_sha": awareness_sha,
        "checkpoint": checkpoint,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w") as handle:
                handle.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    except OSError as error:
        raise DigestStateError(f"cannot save digest state: {error}") from error
