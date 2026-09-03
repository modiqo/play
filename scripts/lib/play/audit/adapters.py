"""Adapter correlation through rote's metadata reads.

``rote adapter info`` is the only subprocess this module runs. It reads what
an installed adapter exposes and where it came from; the adapter itself is
never called.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import Collected, Location
from .package import Package
from .rules import UNKNOWN_ADAPTER, rule
from .steps import StepAnalysis

_TIMEOUT_SECONDS = 4.0


@dataclass
class AdapterInfo:
    adapter_id: str
    operations: set[str] = field(default_factory=set)
    provenance: str | None = None
    fingerprint: str | None = None
    auth_required: bool | None = None
    error: str | None = None


def _rote_home() -> Path:
    override = os.environ.get("ROTE_HOME")
    return Path(override) if override else Path.home() / ".rote"


def _walk_strings(value: Any, key: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for name, item in value.items():
            if name == key and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_walk_strings(item, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_strings(item, key))
    return found


def _operations_from_disk(adapter_id: str) -> set[str]:
    tools = _rote_home() / "adapters" / adapter_id / "tools.json"
    if not tools.is_file():
        return set()
    try:
        payload = json.loads(tools.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    entries = payload if isinstance(payload, list) else payload.get("tools", []) if isinstance(payload, dict) else []
    return {str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry}


def _provenance_from_disk(adapter_id: str) -> tuple[str | None, str | None]:
    root = _rote_home() / "adapters" / adapter_id
    provenance: str | None = None
    fingerprint: str | None = None
    source = root / ".rote-source"
    if source.is_file():
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            provenance = str(payload.get("ref")) if isinstance(payload, dict) and payload.get("ref") else None
        except (OSError, json.JSONDecodeError):
            provenance = None
    manifest = root / "manifest.json"
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            values = _walk_strings(payload, "fingerprint")
            fingerprint = values[0] if values else None
        except (OSError, json.JSONDecodeError):
            fingerprint = None
    return provenance, fingerprint


def read_adapter(adapter_id: str, *, runner: Any = None) -> AdapterInfo:
    """Read one adapter's metadata. ``runner`` is injectable for tests."""
    info = AdapterInfo(adapter_id=adapter_id)
    run = runner or _run_rote_info
    started = time.perf_counter()
    payload: dict[str, Any] | None
    try:
        payload = run(adapter_id)
    except Exception as error:  # noqa: BLE001 - every failure becomes an unknown
        payload = None
        info.error = f"rote adapter info {adapter_id}: {error}"
    if payload is not None:
        result = payload.get("result", payload) if isinstance(payload, dict) else {}
        if isinstance(result, dict):
            toolsets = result.get("toolsets")
            info.operations.update(_walk_strings(toolsets, "name"))
            source = result.get("source")
            if isinstance(source, dict):
                ref = source.get("ref") or source.get("reference")
                info.provenance = str(ref) if ref else None
            identity = result.get("identity")
            if isinstance(identity, dict) and identity.get("fingerprint"):
                info.fingerprint = str(identity["fingerprint"])
            auth = result.get("authentication")
            if isinstance(auth, dict) and "required" in auth:
                info.auth_required = bool(auth["required"])
    if not info.operations:
        info.operations = _operations_from_disk(adapter_id)
    if info.provenance is None or info.fingerprint is None:
        provenance, fingerprint = _provenance_from_disk(adapter_id)
        info.provenance = info.provenance or provenance
        info.fingerprint = info.fingerprint or fingerprint
    if info.error and (info.operations or info.provenance):
        info.error = None  # disk evidence covered what the command could not
    _ = started
    return info


def _run_rote_info(adapter_id: str) -> dict[str, Any] | None:
    completed = subprocess.run(
        ["rote", "adapter", "info", adapter_id, "--json"],
        capture_output=True, text=True, check=False, timeout=_TIMEOUT_SECONDS,
        env={**os.environ, "ROTE_NO_HINTS": "1"},
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[:200] or f"exit {completed.returncode}")
    text = completed.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def adapter_ids(package: Package, steps: StepAnalysis) -> list[str]:
    ids: list[str] = []
    for endpoint in package.frontmatter.endpoints + [s.endpoint or "" for s in steps.shapes]:
        if endpoint.startswith("adapter/"):
            adapter_id = endpoint.split("/", 1)[1]
            if adapter_id and adapter_id not in ids:
                ids.append(adapter_id)
    return ids


def correlate(package: Package, steps: StepAnalysis, infos: dict[str, AdapterInfo]) -> Collected:
    out = Collected()
    sources = package.frontmatter.adapter_sources
    for adapter_id, info in infos.items():
        if info.error:
            out.unknown(UNKNOWN_ADAPTER, f"adapter/{adapter_id}", info.error)
            continue
        for shape in steps.shapes:
            if shape.endpoint == f"adapter/{adapter_id}" and shape.operation and info.operations \
                    and shape.operation not in info.operations:
                out.add(rule("ADAPTER_OPERATION_UNKNOWN").finding(
                    Location(path=f"steps.{shape.name}"), step=shape.name, operation=shape.operation,
                    adapter=adapter_id, known=", ".join(sorted(info.operations))))
        pinned = sources.get(f"adapter/{adapter_id}")
        if pinned and info.provenance and pinned != info.provenance:
            out.add(rule("ADAPTER_SOURCE_PROVENANCE_DIFFERS").finding(
                Location(path=f"adapter_sources.adapter/{adapter_id}"), adapter=adapter_id,
                pinned=pinned, installed=info.provenance))
    return out
