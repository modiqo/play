"""Small owner-private JSON store primitives for Play features."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fcntl


class PrivateStoreError(ValueError):
    """Owner-private state is missing, malformed, or cannot be stored."""


def ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    except OSError as error:
        raise PrivateStoreError(f"cannot prepare private directory {path}: {error}") from error


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise PrivateStoreError(f"cannot load {path}: {error}") from error


def atomic_write_json(path: Path, payload: object) -> None:
    ensure_private_directory(path.parent)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError as error:
        raise PrivateStoreError(f"cannot save {path}: {error}") from error
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def locked_store(root: Path) -> Iterator[None]:
    """Serialize read-modify-write updates without exposing the lock to other users."""

    ensure_private_directory(root)
    lock_path = root / ".lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.chmod(lock_path, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as error:
        raise PrivateStoreError(f"cannot lock private store {root}: {error}") from error
