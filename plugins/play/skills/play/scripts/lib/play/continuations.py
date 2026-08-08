"""Owner-private continuation storage for the multi-process Play CLI."""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

from .controller import RuntimeSession, session_from_dict
from .private_store import PrivateStoreError, atomic_write_json, load_json, locked_store


SCHEMA = "play.runtime-continuation/v1"
MAX_AGE_SECONDS = 24 * 60 * 60
_ID = re.compile(r"^[A-Za-z0-9_-]{24}$")


def default_root() -> Path:
    override = os.environ.get("PLAY_CONTINUATION_DIR")
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".rote" / "play" / "continuations"
    )


def create(session: RuntimeSession, *, root: Path | None = None) -> str:
    store = root or default_root()
    with locked_store(store):
        _prune(store)
        while True:
            continuation_id = secrets.token_urlsafe(18)
            path = store / f"{continuation_id}.json"
            if not path.exists():
                break
        _write(path, session)
    return continuation_id


def load(continuation_id: str, *, root: Path | None = None) -> RuntimeSession:
    store = root or default_root()
    path = _path(store, continuation_id)
    with locked_store(store):
        try:
            payload = load_json(path)
        except FileNotFoundError as error:
            raise PrivateStoreError("Play continuation is missing or expired") from error
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise PrivateStoreError("Play continuation is malformed")
        updated_at = payload.get("updated_at")
        if not isinstance(updated_at, (int, float)) or time.time() - updated_at > MAX_AGE_SECONDS:
            path.unlink(missing_ok=True)
            raise PrivateStoreError("Play continuation is missing or expired")
        session = payload.get("session")
        if not isinstance(session, dict):
            raise PrivateStoreError("Play continuation has no runtime context")
        return session_from_dict(session)


def save(
    continuation_id: str,
    session: RuntimeSession,
    *,
    root: Path | None = None,
) -> None:
    store = root or default_root()
    path = _path(store, continuation_id)
    with locked_store(store):
        if not path.is_file():
            raise PrivateStoreError("Play continuation is missing or expired")
        _write(path, session)


def discard(continuation_id: str, *, root: Path | None = None) -> None:
    store = root or default_root()
    path = _path(store, continuation_id)
    with locked_store(store):
        path.unlink(missing_ok=True)


def _path(root: Path, continuation_id: str) -> Path:
    if not _ID.fullmatch(continuation_id):
        raise PrivateStoreError("Play continuation ID is malformed")
    return root / f"{continuation_id}.json"


def _write(path: Path, session: RuntimeSession) -> None:
    now = time.time()
    atomic_write_json(
        path,
        {
            "schema": SCHEMA,
            "updated_at": now,
            "session": session.as_dict(),
        },
    )


def _prune(root: Path) -> None:
    cutoff = time.time() - MAX_AGE_SECONDS
    for path in root.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue
