"""Persist audit envelopes under Play's home, by Play id, with history.

Layout::

    <PLAY_HOME>/audit/plays/<owner>/<name>/
        index.json                 latest envelope per version, by digest
        <version>/<digest>.json    one envelope per package digest per host profile
        history.jsonl              append-only: audits, handoffs, deltas

Every write is atomic and best-effort. A failure is returned as a string so
the runner can record it as an unknown; nothing here raises to a caller.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def play_home() -> Path:
    configured = os.environ.get("PLAY_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".play"


def _safe(segment: str) -> str:
    return _SAFE.sub("_", segment).strip("_") or "_"


def _play_dir(reference: str) -> Path:
    owner, _, name = reference.replace("https://play.modiqo.ai/", "").partition("/")
    name = name.split("@", 1)[0] if name else owner
    owner = owner if name != owner else "local"
    return play_home() / "audit" / "plays" / _safe(owner) / _safe(name)


def _digest_key(digest: str) -> str:
    return _safe(digest.replace("sha256:", "")[:24])


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def persist(envelope: dict[str, Any]) -> tuple[str | None, str | None]:
    """Write the envelope; return (stored path, error)."""
    subject = envelope.get("subject") or {}
    reference = str(subject.get("reference") or "local/unknown")
    version = _safe(str(subject.get("version") or "unversioned"))
    digest = str(subject.get("digest") or "nodigest")
    profile = _safe(str((envelope.get("host") or {}).get("profile") or "live"))
    try:
        directory = _play_dir(reference)
        target = directory / version / f"{_digest_key(digest)}.{profile}.json"
        _atomic_write(target, json.dumps(envelope, indent=1, sort_keys=True))
        index_path = directory / "index.json"
        index: dict[str, Any] = {}
        if index_path.is_file():
            try:
                loaded = json.loads(index_path.read_text(encoding="utf-8"))
                index = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                index = {}
        index[version] = {
            "digest": digest,
            "profile": profile,
            "path": str(target.relative_to(directory)),
            "audited_at": envelope.get("subject", {}).get("audited_at"),
            "open_facts": (envelope.get("summary") or {}).get("open_facts"),
            "unknowns": (envelope.get("summary") or {}).get("unknowns"),
        }
        _atomic_write(index_path, json.dumps(index, indent=1, sort_keys=True))
        append_history(reference, {
            "event": "audit",
            "at": envelope.get("subject", {}).get("audited_at"),
            "version": version,
            "digest": digest,
            "profile": profile,
            "open_facts": (envelope.get("summary") or {}).get("open_facts"),
            "judgments": (envelope.get("summary") or {}).get("judgments"),
            "unknowns": (envelope.get("summary") or {}).get("unknowns"),
            "path": str(target.relative_to(directory)),
        })
        return str(target), None
    except Exception as error:  # noqa: BLE001 - persistence is best-effort by contract
        return None, f"audit store: {error}"


def append_history(reference: str, entry: dict[str, Any]) -> str | None:
    try:
        directory = _play_dir(reference)
        directory.mkdir(parents=True, exist_ok=True)
        entry = {"at": entry.get("at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}
        with (directory / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return None
    except Exception as error:  # noqa: BLE001
        return f"audit history: {error}"


def history(reference: str) -> list[dict[str, Any]]:
    path = _play_dir(reference) / "history.jsonl"
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            entries.append(loaded)
    return entries


def load(reference: str, *, digest: str | None = None, version: str | None = None) -> dict[str, Any] | None:
    directory = _play_dir(reference)
    index_path = directory / "index.json"
    if digest is None:
        if not index_path.is_file():
            return None
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(index, dict) or not index:
            return None
        key = version or sorted(index)[-1]
        entry = index.get(key)
        if not isinstance(entry, dict):
            return None
        path = directory / str(entry.get("path"))
    else:
        matches = sorted(directory.rglob(f"{_digest_key(digest)}.*.json"))
        if not matches:
            return None
        path = matches[-1]
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def delta(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """What closed, what remains, what is new, keyed by rule id and location."""
    def keys(envelope: dict[str, Any] | None) -> set[str]:
        if not envelope:
            return set()
        result: set[str] = set()
        for section in ("facts", "judgments"):
            for item in envelope.get(section) or []:
                location = item.get("location") or {}
                marker = location.get("path") or f"{location.get('file')}:{location.get('line')}"
                result.add(f"{item.get('id')}@{marker}")
        return result
    before, after = keys(previous), keys(current)
    return {
        "closed": sorted(before - after),
        "remaining": sorted(before & after),
        "new": sorted(after - before),
        "digest_before": (previous or {}).get("subject", {}).get("digest"),
        "digest_after": current.get("subject", {}).get("digest"),
    }
