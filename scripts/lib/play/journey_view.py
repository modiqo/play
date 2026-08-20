"""Owner-private localhost server for the live Play Journey map."""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections.abc import Mapping
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .journey import (
    _capture,
    _journey_key,
    _load_source,
    _snapshot_path,
    _standby_path,
    _worker_path,
    journey_directory,
    load_graph,
    load_snapshot,
    refresh_capture,
    schedule_worker,
)
from .journey_capabilities import capability_descriptor
from .journal import recalled_play_origins
from .journey_scene import JourneySceneError, build_scene
from .journey_story import build_story
from .private_store import atomic_write_json, load_json


VIEWER_SCHEMA = "play.journey-viewer/v1"
ASSET_ROOT = Path(__file__).with_name("journey_viewer")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
MAX_LIFETIME_SECONDS = 8 * 60 * 60
PROJECTION_START_TIMEOUT_SECONDS = 4.0
LIVE_ACTIVITY_WINDOW_SECONDS = 30.0
INTERACTIONS_SCHEMA = "play.journey-interactions/v1"
EXCHANGE_SCHEMA = "play.journey-exchange/v1"
MAX_EXCHANGE_CHARS = 24_000
MAX_COLLECTION_ITEMS = 80
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|token|secret|password|passwd|api[_-]?key|private[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+"),
    re.compile(r"(?i)([?&](?:access_token|token|api_key|key|secret)=)[^&#\s]+"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
)


def _workspace_activity(workspace_path: Path | None) -> tuple[float | None, bool]:
    """Return a bounded workspace heartbeat without scanning the workspace tree."""

    if workspace_path is None:
        return None, False
    rote_root = workspace_path / ".rote"
    candidates = (
        rote_root / "workspace.db",
        rote_root / "workspace.db-wal",
        rote_root / "responses",
    )
    modified: list[float] = []
    for candidate in candidates:
        try:
            stat = candidate.stat()
        except OSError:
            continue
        if candidate.name == "workspace.db-wal" and stat.st_size == 0:
            continue
        modified.append(stat.st_mtime)
    if not modified:
        return None, False
    activity_epoch = max(modified)
    return activity_epoch, time.time() - activity_epoch <= LIVE_ACTIVITY_WINDOW_SECONDS


def _rote_workspace_root() -> Path:
    """Return Rote's canonical workspace root, honoring its test override."""

    rote_home = os.environ.get("ROTE_HOME")
    return (Path(rote_home) if rote_home else Path.home() / ".rote") / "rote" / "workspaces"


def _rote_workspaces() -> list[Path]:
    """List current Rote workspaces without descending into their evidence."""

    workspace_root = _rote_workspace_root()
    try:
        candidates = [
            path
            for path in workspace_root.iterdir()
            if not path.name.startswith(".")
            and path.is_dir()
            and (path / ".rote" / "workspace.db").is_file()
        ]
    except OSError:
        return []

    def recency(path: Path) -> tuple[int, str]:
        database = path / ".rote" / "workspace.db"
        try:
            modified = database.stat().st_mtime_ns
        except OSError:
            try:
                modified = path.stat().st_mtime_ns
            except OSError:
                modified = 0
        return modified, path.name

    return sorted(candidates, key=recency, reverse=True)


def _canonical_path(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path.absolute())


def _workspace_reference(workspace_path: Path) -> str:
    digest = hashlib.sha256(_canonical_path(workspace_path).encode()).hexdigest()
    return f"workspace:{digest}"


def _workspace_intent(workspace_path: Path) -> str:
    label = re.sub(r"^(?:dag|play-capture)-", "", workspace_path.name)
    label = re.sub(r"-[0-9a-f]{8,}$", "", label)
    return re.sub(r"[-_]+", " ", label).strip().capitalize() or "Rote workspace"


def _reference_slug(reference: str) -> str | None:
    value = urllib.parse.urlparse(reference)
    path = value.path if value.scheme == "https" else reference
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return None
    return segments[-1].split("@", 1)[0] or None


def _workspace_recall_origin(workspace_path: Path) -> dict[str, Any] | None:
    """Join recall provenance by exact workspace, then legacy namespace+time."""

    origins = recalled_play_origins()
    exact = [item for item in origins if item.get("workspace") == workspace_path.name]
    candidates = exact
    association_basis = "typed_workspace"
    if not candidates:
        prefix = workspace_path.name.rsplit("-", 1)[0]
        candidates = [
            item
            for item in origins
            if (slug := _reference_slug(str(item.get("exact_reference") or "")))
            and prefix == f"dag-{slug}"
        ]
        association_basis = "rote_namespace_time"
        try:
            workspace_epoch = (workspace_path / ".rote" / "workspace.db").stat().st_mtime
        except OSError:
            return None
        recent: list[dict[str, Any]] = []
        for item in candidates:
            occurred_at = item.get("last_at")
            if not isinstance(occurred_at, str):
                continue
            try:
                event_epoch = datetime.fromisoformat(occurred_at).timestamp()
            except ValueError:
                continue
            if abs(event_epoch - workspace_epoch) <= 300:
                recent.append(item)
        candidates = recent
    if not candidates:
        return None
    origin = max(candidates, key=lambda item: str(item.get("last_at") or ""))
    return {
        "kind": "recalled_play",
        "run_id": origin.get("run_id"),
        "exact_reference": origin.get("exact_reference"),
        "association_basis": association_basis,
        "exploration_skipped": True,
    }


def _workspace_capture(workspace_path: Path) -> dict[str, Any]:
    origin = _workspace_recall_origin(workspace_path)
    return {
        "reference": _workspace_reference(workspace_path),
        "intent": _workspace_intent(workspace_path),
        "status": "recorded",
        "workspace": workspace_path.name,
        "workspace_path": str(workspace_path),
        **({"origin": origin} if origin is not None else {}),
    }


_workspace_projection_guard = threading.Lock()
_workspace_projections: set[str] = set()


def _schedule_workspace_projection(
    capture: Mapping[str, Any], *, root: Path | None = None
) -> bool:
    """Project an unregistered Rote workspace without mutating Play capture state."""

    reference = capture.get("reference")
    if not isinstance(reference, str) or not reference:
        return False
    with _workspace_projection_guard:
        if reference in _workspace_projections:
            return True
        _workspace_projections.add(reference)

    def project() -> None:
        try:
            refresh_capture(capture, root=root, force=True)
        except Exception:  # noqa: BLE001 - background projection cannot break the viewer
            pass
        finally:
            with _workspace_projection_guard:
                _workspace_projections.discard(reference)

    threading.Thread(
        target=project,
        name=f"play-journey-{hashlib.sha256(reference.encode()).hexdigest()[:8]}",
        daemon=True,
    ).start()
    return True


class JourneyViewError(RuntimeError):
    """The local Journey viewer could not be started safely."""


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_TEXT:
        redacted = pattern.sub(
            (lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]"),
            redacted,
        )
    return redacted


def _redact_exchange_value(value: object, *, depth: int = 0) -> object:
    """Return a bounded display copy without credential-bearing fields."""

    if depth > 10:
        return "[DEPTH LIMIT]"
    if isinstance(value, Mapping):
        mapped: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                mapped["…"] = f"{len(value) - MAX_COLLECTION_ITEMS} fields omitted"
                break
            key = str(raw_key)
            mapped[key] = (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(key)
                else _redact_exchange_value(item, depth=depth + 1)
            )
        return mapped
    if isinstance(value, list):
        items = value[:MAX_COLLECTION_ITEMS]
        listed = [_redact_exchange_value(item, depth=depth + 1) for item in items]
        if len(value) > MAX_COLLECTION_ITEMS:
            listed.append(f"[{len(value) - MAX_COLLECTION_ITEMS} ITEMS OMITTED]")
        return listed
    if isinstance(value, str):
        return _redact_text(value[:MAX_EXCHANGE_CHARS])
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_text(str(value)[:MAX_EXCHANGE_CHARS])


def _bounded_exchange(value: object) -> tuple[object, bool]:
    redacted = _redact_exchange_value(value)
    encoded = json.dumps(redacted, sort_keys=True, ensure_ascii=True)
    if len(encoded) <= MAX_EXCHANGE_CHARS:
        return redacted, False
    return {
        "preview": encoded[:MAX_EXCHANGE_CHARS],
        "notice": "Display truncated; the complete evidence remains in the owner-private Rote workspace.",
    }, True


def _interaction_projection(capture_ref: str, *, root: Path | None = None) -> dict[str, Any]:
    """Map every preserved Rote command to its semantic site without payloads."""

    source = _load_source(capture_ref, root=root)
    graph = source.get("graph")
    graph = graph if isinstance(graph, Mapping) else {}
    activities = {
        int(item["sequence"]): item
        for item in source.get("activities", [])
        if isinstance(item, Mapping) and isinstance(item.get("sequence"), int)
    }
    sites: dict[str, list[dict[str, Any]]] = {}
    assigned: set[int] = set()
    for node in graph.get("nodes", []):
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            continue
        evidence = node.get("evidence")
        evidence = evidence if isinstance(evidence, Mapping) else {}
        commands = evidence.get("rote_commands")
        commands = commands if isinstance(commands, list) else []
        interactions: list[dict[str, Any]] = []
        for sequence in commands:
            if not isinstance(sequence, int) or sequence in assigned:
                continue
            activity = activities.get(sequence)
            if activity is None:
                continue
            assigned.add(sequence)
            command_type = str(activity.get("command_type") or "Unknown")
            operation = str(activity.get("operation") or "interaction")
            provider = (
                activity.get("provider")
                if isinstance(activity.get("provider"), str)
                else None
            )
            capability = activity.get("capability")
            if not isinstance(capability, Mapping):
                # Journeys projected before rules-v3 do not carry structured
                # capability metadata.  Derive a safe compatibility descriptor
                # from the persisted command type and display operation so old
                # maps do not collapse every CLI into "Rote workspace".
                legacy_payload: dict[str, Any] = {}
                if command_type.startswith("Process") or command_type == "StreamFollow":
                    program = operation.split(maxsplit=1)[0] if operation else "process"
                    legacy_payload = {"invocation": {"program": program, "args": []}}
                capability = capability_descriptor(
                    command_type,
                    legacy_payload,
                    operation,
                    provider,
                )
            interactions.append(
                {
                    "sequence": sequence,
                    "command_type": command_type,
                    "operation": operation,
                    "provider": provider,
                    "capability": dict(capability),
                    "effect_profile": dict(activity["effect_profile"])
                    if isinstance(activity.get("effect_profile"), Mapping)
                    else {
                        "schema": "play.journey-effect/v1",
                        "posture": str(activity.get("effect") or "unknown"),
                        "scopes": [],
                        "source": "legacy_projection",
                        "confidence": "unknown",
                        "destructive": None,
                    },
                    "effect": activity.get("effect")
                    if isinstance(activity.get("effect"), str)
                    else None,
                    "status": str(activity.get("status") or "unknown"),
                    "duration_ms": int(activity.get("duration_ms") or 0),
                    "tokens": int(activity.get("tokens") or 0),
                    "tokens_saved": int(activity.get("tokens_saved") or 0),
                    "response_refs": [
                        ref
                        for ref in activity.get("response_refs", [])
                        if isinstance(ref, str)
                    ],
                    "timestamp": activity.get("timestamp")
                    if isinstance(activity.get("timestamp"), str)
                    else None,
                }
            )
        sites[str(node["id"])] = sorted(interactions, key=lambda item: item["sequence"])
    return {
        "schema": INTERACTIONS_SCHEMA,
        "journey_key": str(graph.get("journey_key") or ""),
        "sites": sites,
        "total": len(assigned),
    }


def _exchange_projection(
    capture_ref: str, sequence: int, *, root: Path | None = None
) -> dict[str, Any] | None:
    """Lazily read one owner-private Rote exchange for a selected tower."""

    interaction = _interaction_projection(capture_ref, root=root)
    allowed = {
        int(item["sequence"])
        for items in interaction["sites"].values()
        for item in items
    }
    if sequence not in allowed:
        return None
    capture = _capture(capture_ref)
    workspace_value = capture.get("workspace_path") if isinstance(capture, Mapping) else None
    if not isinstance(workspace_value, str):
        return None
    workspace = Path(workspace_value)
    database = workspace / ".rote" / "workspace.db"
    if not database.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT command_type, params, response_ids, timestamp "
            "FROM command_log WHERE sequence = ?",
            (sequence,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()
    if row is None:
        return None
    try:
        command_value = json.loads(row["params"])
    except (TypeError, json.JSONDecodeError):
        command_value = {"command_type": row["command_type"]}
    try:
        response_ids = json.loads(row["response_ids"])
    except (TypeError, json.JSONDecodeError):
        response_ids = []
    response_ids = [value for value in response_ids if isinstance(value, int)]
    request_value: object = command_value
    response_value: object = None
    tokens: object = {}
    if response_ids:
        envelope_path = workspace / ".rote" / "responses" / f"@{response_ids[0]}.json"
        try:
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            envelope = {}
        if isinstance(envelope, Mapping):
            request_value = envelope.get("request", command_value)
            response_value = envelope.get("response")
            tokens = envelope.get("tokens") if isinstance(envelope.get("tokens"), Mapping) else {}
    request, request_truncated = _bounded_exchange(request_value)
    response, response_truncated = _bounded_exchange(response_value)
    return {
        "schema": EXCHANGE_SCHEMA,
        "sequence": sequence,
        "command_type": str(row["command_type"]),
        "timestamp": str(row["timestamp"]),
        "response_refs": [f"@{value}" for value in response_ids],
        "request": request,
        "response": response,
        "tokens": _redact_exchange_value(tokens),
        "redacted": True,
        "truncated": request_truncated or response_truncated,
    }


def _workspace_catalog(
    selected_ref: str, *, root: Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Overlay Play captures on the workspaces that currently exist in Rote.

    The Rote workspace root is authoritative for archive membership. Old
    capture and Journey records remain recoverable on disk, but do not leak
    back into a clean-slate archive after their source workspace is moved.
    """

    try:
        store = load_json(_standby_path())
    except (OSError, ValueError):
        store = {}
    captures = store.get("captures") if isinstance(store, Mapping) else None
    capture_items = captures if isinstance(captures, list) else []
    captures_by_workspace: dict[str, Mapping[str, Any]] = {}
    for value in capture_items:
        if not isinstance(value, Mapping):
            continue
        reference = value.get("reference")
        workspace_value = value.get("workspace_path")
        if (
            isinstance(reference, str)
            and reference
            and isinstance(workspace_value, str)
            and workspace_value
        ):
            captures_by_workspace[_canonical_path(Path(workspace_value))] = value

    summaries: list[dict[str, Any]] = []
    lookup: dict[str, str] = {}
    for workspace_path in _rote_workspaces():
        capture = captures_by_workspace.get(_canonical_path(workspace_path))
        evidence_available = (workspace_path / ".rote" / "workspace.db").is_file()
        activity_epoch, active_recently = _workspace_activity(workspace_path)
        if capture is None:
            workspace_capture = _workspace_capture(workspace_path)
            reference = str(workspace_capture["reference"])
            workspace_id = _journey_key(reference)
            lookup[workspace_id] = reference
            graph = load_graph(reference, root=root) if evidence_available else None
            telemetry = graph.get("telemetry") if isinstance(graph, Mapping) else {}
            summaries.append(
                {
                    "id": workspace_id,
                    "intent": str(workspace_capture["intent"]),
                    "workspace": workspace_path.name,
                    "workspace_path": str(workspace_path),
                    "created_at": None,
                    "capture_state": "workspace",
                    "live": False,
                    "activity_epoch": activity_epoch,
                    "active_recently": active_recently,
                    "selected": False,
                    "workspace_available": True,
                    "evidence_available": evidence_available,
                    "graph_ready": graph is not None,
                    "projectable": evidence_available,
                    "nodes": len(graph.get("nodes", [])) if isinstance(graph, Mapping) else 0,
                    "edges": len(graph.get("edges", [])) if isinstance(graph, Mapping) else 0,
                    "commands": int(telemetry.get("commands") or 0)
                    if isinstance(telemetry, Mapping)
                    else 0,
                }
            )
            continue

        reference = str(capture["reference"])
        workspace_id = _journey_key(reference)
        lookup[workspace_id] = reference
        graph = load_graph(reference, root=root) if evidence_available else None
        try:
            worker = load_json(_worker_path(reference, root=root))
        except (OSError, ValueError):
            worker = {}
        live = bool(
            isinstance(worker, Mapping)
            and worker.get("state") == "running"
            and _pid_running(worker.get("pid"))
        )
        telemetry = graph.get("telemetry") if isinstance(graph, Mapping) else {}
        summaries.append(
            {
                "id": workspace_id,
                "intent": str(capture.get("intent") or "Untitled exploration"),
                "workspace": str(capture.get("workspace") or workspace_path.name),
                "workspace_path": str(workspace_path),
                "created_at": capture.get("created_at"),
                "capture_state": str(capture.get("status") or "unknown"),
                "live": live,
                "activity_epoch": activity_epoch,
                "active_recently": active_recently,
                "selected": reference == selected_ref,
                "workspace_available": True,
                "evidence_available": evidence_available,
                "graph_ready": graph is not None,
                "projectable": evidence_available,
                "nodes": len(graph.get("nodes", [])) if isinstance(graph, Mapping) else 0,
                "edges": len(graph.get("edges", [])) if isinstance(graph, Mapping) else 0,
                "commands": int(telemetry.get("commands") or 0)
                if isinstance(telemetry, Mapping)
                else 0,
            }
        )

    # Explicit graph roots used by tests and offline exports have no Rote home.
    # Preserve that mode without resurrecting a real capture whose workspace
    # was deliberately moved out of the canonical root.
    if (
        root is not None
        and selected_ref not in lookup.values()
        and _capture(selected_ref) is None
    ):
        workspace_id = _journey_key(selected_ref)
        lookup[workspace_id] = selected_ref
        graph = load_graph(selected_ref, root=root)
        summaries.append(
            {
                "id": workspace_id,
                "intent": str(graph.get("intent", {}).get("label") or "Active exploration")
                if isinstance(graph, Mapping)
                else "Active exploration",
                "workspace": "captured workspace",
                "workspace_path": None,
                "created_at": graph.get("created_at") if isinstance(graph, Mapping) else None,
                "capture_state": graph.get("state", "unknown") if isinstance(graph, Mapping) else "unknown",
                "live": False,
                "activity_epoch": None,
                "active_recently": False,
                "selected": True,
                "workspace_available": False,
                "evidence_available": False,
                "graph_ready": graph is not None,
                "projectable": graph is not None,
                "nodes": len(graph.get("nodes", [])) if isinstance(graph, Mapping) else 0,
                "edges": len(graph.get("edges", [])) if isinstance(graph, Mapping) else 0,
                "commands": 0,
            }
        )
    return summaries, lookup


def _selected_workspace_id(workspaces: list[dict[str, Any]]) -> str:
    selected = next((item for item in workspaces if item.get("selected")), None)
    if selected is not None:
        return str(selected["id"])
    usable = next((item for item in workspaces if item.get("graph_ready")), None)
    if usable is None:
        usable = next((item for item in workspaces if item.get("projectable")), None)
    return str(usable["id"]) if usable is not None else ""


def _workspace_index(selected_ref: str, *, root: Path | None = None) -> dict[str, Any]:
    workspaces, _lookup = _workspace_catalog(selected_ref, root=root)
    return {
        "schema": "play.journey-workspace-index/v1",
        "selected_id": _selected_workspace_id(workspaces),
        "workspace_root": str(_rote_workspace_root()),
        "workspaces": workspaces,
    }


def _catalog_capture(item: Mapping[str, Any], reference: str) -> Mapping[str, Any] | None:
    capture = _capture(reference)
    if capture is not None:
        return capture
    workspace_value = item.get("workspace_path")
    if not isinstance(workspace_value, str) or not workspace_value:
        return None
    workspace_path = Path(workspace_value)
    if reference != _workspace_reference(workspace_path):
        return None
    return _workspace_capture(workspace_path)


def _refresh_workspace_catalog(
    selected_ref: str, *, root: Path | None = None
) -> dict[str, Any]:
    """Rescan current workspaces and restart only their derived projectors."""

    workspaces, lookup = _workspace_catalog(selected_ref, root=root)
    scheduled = 0
    for item in workspaces:
        if not item.get("projectable"):
            continue
        reference = lookup.get(str(item.get("id") or ""))
        capture = _catalog_capture(item, reference) if reference else None
        if capture is None:
            continue
        registered = _capture(reference) if reference else None
        started = (
            schedule_worker(capture)
            if registered is not None
            else _schedule_workspace_projection(capture, root=root)
        )
        if started:
            scheduled += 1

    try:
        store = load_json(_standby_path())
    except (OSError, ValueError):
        store = {}
    captures = store.get("captures") if isinstance(store, Mapping) else []
    retained_refs = set(lookup.values())
    stale = (
        sum(
            1
            for capture in captures
            if isinstance(capture, Mapping)
            and isinstance(capture.get("reference"), str)
            and capture.get("reference") not in retained_refs
        )
        if isinstance(captures, list)
        else 0
    )

    refreshed, _refreshed_lookup = _workspace_catalog(selected_ref, root=root)
    return {
        "schema": "play.journey-workspace-index/v1",
        "selected_id": _selected_workspace_id(refreshed),
        "workspace_root": str(_rote_workspace_root()),
        "workspaces": refreshed,
        "reconciliation": {
            "current_workspaces": len(refreshed),
            "mapped_captures": sum(
                1
                for item in refreshed
                if item.get("workspace_available")
                and item.get("capture_state") != "workspace"
            ),
            "stale_captures_hidden": stale,
            "projectors_scheduled": scheduled,
        },
    }


def _ensure_graph_ready(
    capture_ref: str,
    *,
    root: Path | None = None,
    timeout_seconds: float = PROJECTION_START_TIMEOUT_SECONDS,
) -> None:
    """Start a missed projector and wait briefly for its first generation."""

    if load_graph(capture_ref, root=root) is not None:
        return
    capture = _capture(capture_ref)
    if capture is None:
        raise JourneyViewError("The captured exploration is missing or expired")
    if not schedule_worker(capture):
        raise JourneyViewError(
            "The Journey projector could not be started; check whether "
            "PLAY_JOURNEY_DISABLE is set, then retry"
        )
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while time.monotonic() < deadline:
        if load_graph(capture_ref, root=root) is not None:
            return
        time.sleep(0.05)
    raise JourneyViewError(
        "The Journey projector started but its first graph is not ready yet; retry in a moment"
    )


def _viewer_state_path(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "viewer.json"


def _viewer_asset_sha256() -> str:
    digest = hashlib.sha256()
    for name in ("index.html", "viewer.css", "viewer.js"):
        digest.update(name.encode())
        digest.update((ASSET_ROOT / name).read_bytes())
    return "sha256:" + digest.hexdigest()


def _viewer_implementation_sha256() -> str:
    """Fingerprint both the browser bundle and its resident Python server."""

    digest = hashlib.sha256()
    digest.update(_viewer_asset_sha256().encode())
    module_root = Path(__file__).parent
    for path in sorted(module_root.glob("journey*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _pid_running(pid: object) -> bool:
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _existing_viewer(capture_ref: str, *, root: Path | None = None) -> dict[str, Any] | None:
    try:
        value = load_json(_viewer_state_path(capture_ref, root=root))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != VIEWER_SCHEMA
        or not _pid_running(value.get("pid"))
        or not isinstance(value.get("url"), str)
        or value.get("asset_sha256") != _viewer_asset_sha256()
        or value.get("implementation_sha256") != _viewer_implementation_sha256()
    ):
        return None
    return dict(value)


def _security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")


def _handler_type(
    capture_ref: str, token: str, *, root: Path | None = None
) -> type[BaseHTTPRequestHandler]:
    cookie_name = f"play_journey_{hashlib.sha256(token.encode()).hexdigest()[:12]}"

    class JourneyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *arguments: object) -> None:
            del format, arguments
            return

        def _authorized(self, query: Mapping[str, list[str]]) -> bool:
            supplied = query.get("token", [""])[0]
            if secrets.compare_digest(supplied, token):
                return True
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except Exception:  # pragma: no cover - defensive parser boundary
                return False
            morsel = cookies.get(cookie_name)
            return morsel is not None and secrets.compare_digest(morsel.value, token)

        def _send_bytes(
            self,
            payload: bytes,
            content_type: str,
            *,
            status: int = 200,
            establish_session: bool = False,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if establish_session:
                self.send_header(
                    "Set-Cookie",
                    f"{cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={MAX_LIFETIME_SECONDS}",
                )
            _security_headers(self)
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload: object, *, status: int = 200, etag: str | None = None) -> None:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            if etag:
                self.send_header("ETag", etag)
            _security_headers(self)
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            asset_name = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
            # The application shell is public and contains no captured data. Keeping it
            # reloadable lets the browser recover the API token from sessionStorage;
            # every workspace, story, scene, and event endpoint remains token-gated.
            if asset_name in {"index.html", "viewer.css", "viewer.js"}:
                path = ASSET_ROOT / asset_name
                try:
                    payload = path.read_bytes()
                except OSError:
                    self._send_json({"error": "viewer_asset_missing"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_bytes(
                    payload,
                    CONTENT_TYPES[path.suffix],
                    establish_session=asset_name == "index.html" and self._authorized(query),
                )
                return
            if not self._authorized(query):
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/workspaces":
                self._send_json(_workspace_index(capture_ref, root=root))
                return
            _workspaces, workspace_lookup = _workspace_catalog(capture_ref, root=root)
            requested_workspace = query.get("workspace", [""])[0]
            selected_capture = workspace_lookup.get(requested_workspace, capture_ref)
            if parsed.path == "/api/scene":
                graph = load_graph(selected_capture, root=root)
                if graph is None:
                    self._send_json({"error": "journey_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                try:
                    scene = build_scene(graph)
                except JourneySceneError as error:
                    self._send_json({"error": str(error)}, status=HTTPStatus.CONFLICT)
                    return
                etag = f'"{scene["scene_sha256"]}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    _security_headers(self)
                    self.end_headers()
                    return
                self._send_json(scene, etag=etag)
                return
            if parsed.path == "/api/story":
                graph = load_graph(selected_capture, root=root)
                if graph is None:
                    self._send_json({"error": "journey_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                story = build_story(graph)
                etag = f'"{story["story_sha256"]}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    _security_headers(self)
                    self.end_headers()
                    return
                self._send_json(story, etag=etag)
                return
            if parsed.path == "/api/interactions":
                graph = load_graph(selected_capture, root=root)
                if graph is None:
                    self._send_json({"error": "journey_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(_interaction_projection(selected_capture, root=root))
                return
            if parsed.path == "/api/exchange":
                raw_sequence = query.get("sequence", [""])[0]
                try:
                    sequence = int(raw_sequence)
                except ValueError:
                    self._send_json({"error": "interaction_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                exchange = _exchange_projection(selected_capture, sequence, root=root)
                if exchange is None:
                    self._send_json({"error": "interaction_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(exchange)
                return
            if parsed.path == "/api/events":
                self._events(selected_capture)
                return
            if asset_name != "index.html":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if not self._authorized(query):
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/refresh":
                self._send_json(_refresh_workspace_catalog(capture_ref, root=root))
                return
            if parsed.path != "/api/project":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            _workspaces, workspace_lookup = _workspace_catalog(capture_ref, root=root)
            requested_workspace = query.get("workspace", [""])[0]
            selected_capture = workspace_lookup.get(requested_workspace)
            if selected_capture is None:
                self._send_json({"error": "workspace_unavailable"}, status=HTTPStatus.NOT_FOUND)
                return
            if load_graph(selected_capture, root=root) is not None:
                self._send_json({"status": "ready", "workspace": requested_workspace})
                return
            selected_item = next(
                (item for item in _workspaces if item.get("id") == requested_workspace),
                None,
            )
            capture = (
                _catalog_capture(selected_item, selected_capture)
                if selected_item is not None
                else None
            )
            if capture is None:
                self._send_json({"error": "workspace_unavailable"}, status=HTTPStatus.NOT_FOUND)
                return
            registered = _capture(selected_capture)
            started = (
                schedule_worker(capture)
                if registered is not None
                else _schedule_workspace_projection(capture, root=root)
            )
            if not started:
                self._send_json(
                    {"error": "projector_unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE
                )
                return
            self._send_json(
                {"status": "projecting", "workspace": requested_workspace},
                status=HTTPStatus.ACCEPTED,
            )

        def _events(self, selected_capture: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            _security_headers(self)
            self.end_headers()
            last_fingerprint: tuple[int, int] | None = None
            while True:
                try:
                    stat = _snapshot_path(selected_capture, root=root).stat()
                    fingerprint = (stat.st_size, stat.st_mtime_ns)
                    if fingerprint != last_fingerprint:
                        snapshot = load_snapshot(selected_capture, root=root)
                        event = {
                            "generation": snapshot.get("generation") if snapshot else None,
                            "material_generation": snapshot.get("material_generation") if snapshot else None,
                        }
                        encoded = json.dumps(event, separators=(",", ":"))
                        self.wfile.write(f"event: journey\ndata: {encoded}\n\n".encode())
                        self.wfile.flush()
                        last_fingerprint = fingerprint
                    else:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    time.sleep(0.75)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

    return JourneyHandler


def make_server(
    capture_ref: str,
    token: str,
    *,
    root: Path | None = None,
    port: int = 0,
) -> ThreadingHTTPServer:
    """Create a loopback-only viewer server; caller owns its lifecycle."""

    server = ThreadingHTTPServer(
        ("127.0.0.1", port),
        _handler_type(capture_ref, token, root=root),
    )
    server.daemon_threads = True
    return server


def serve_viewer(
    capture_ref: str,
    token: str,
    *,
    root: Path | None = None,
    port: int = 0,
    lifetime_seconds: int = MAX_LIFETIME_SECONDS,
) -> int:
    server = make_server(capture_ref, token, root=root, port=port)
    server.timeout = 1.0
    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}/?token={urllib.parse.quote(token)}"
    atomic_write_json(
        _viewer_state_path(capture_ref, root=root),
        {
            "schema": VIEWER_SCHEMA,
            "pid": os.getpid(),
            "port": actual_port,
            "url": url,
            "asset_sha256": _viewer_asset_sha256(),
            "implementation_sha256": _viewer_implementation_sha256(),
            "started_at_epoch": time.time(),
        },
    )
    started = time.monotonic()
    try:
        while time.monotonic() - started < max(1, lifetime_seconds):
            server.handle_request()
    finally:
        server.server_close()
    return 0


def launch_viewer(
    capture_ref: str,
    *,
    root: Path | None = None,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Start or reuse the detached viewer without delaying exploration."""

    _ensure_graph_ready(capture_ref, root=root)
    existing = _existing_viewer(capture_ref, root=root)
    if existing is not None:
        if open_browser:
            webbrowser.open(str(existing["url"]))
        return existing
    token = secrets.token_urlsafe(24)
    executable = Path(sys.argv[0]).resolve()
    environment = os.environ.copy()
    if root is not None:
        environment["PLAY_JOURNEY_ROOT"] = str(root)
    command = [
        sys.executable,
        str(executable),
        "serve",
        "--capture",
        capture_ref,
        "--viewer-token",
        token,
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    deadline = time.monotonic() + 3.0
    state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = _existing_viewer(capture_ref, root=root)
        if state is not None and state.get("pid") == process.pid:
            break
        time.sleep(0.05)
    if state is None or state.get("pid") != process.pid:
        raise JourneyViewError("The local Journey viewer did not become ready")
    if open_browser:
        webbrowser.open(str(state["url"]))
    return state
