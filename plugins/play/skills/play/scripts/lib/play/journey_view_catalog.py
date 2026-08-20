"""Rote workspace discovery and reconciliation for the Journey viewer."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import urllib.parse
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .journal import recalled_play_origins
from .journey import (
    _capture,
    _journey_key,
    _standby_path,
    _worker_path,
    load_graph,
    refresh_capture,
    schedule_worker,
)
from .private_store import load_json
from .journey_tutorial import TUTORIAL_REFERENCE, TUTORIAL_WORKSPACE_ID, ensure_tutorial


LIVE_ACTIVITY_WINDOW_SECONDS = 30.0


def _journey_mode(capture_state: object) -> str:
    """Classify whether a captured journey can still grow."""

    return "live" if str(capture_state or "") == "active" else "recorded"


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
        activity_epoch, _active_recently = _workspace_activity(path)
        modified = int(activity_epoch * 1_000_000_000) if activity_epoch is not None else 0
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


def _workspace_capture(
    workspace_path: Path, *, status: str = "recorded"
) -> dict[str, Any]:
    origin = _workspace_recall_origin(workspace_path)
    return {
        "reference": _workspace_reference(workspace_path),
        "intent": _workspace_intent(workspace_path),
        "status": status,
        "workspace": workspace_path.name,
        "workspace_path": str(workspace_path),
        **({"origin": origin} if origin is not None else {}),
    }


def _active_workspace_capture(
    *, standby_path: Path | None = None, cwd: Path | None = None
) -> dict[str, Any] | None:
    """Resolve the current Rote workspace, overlaying matching Play metadata."""

    workspaces = _rote_workspaces()
    if not workspaces:
        return None
    current = cwd
    if current is None:
        try:
            current = Path.cwd()
        except OSError:
            current = None
    selected = None
    if current is not None:
        canonical_current = Path(_canonical_path(current))
        for workspace in workspaces:
            try:
                canonical_current.relative_to(Path(_canonical_path(workspace)))
            except ValueError:
                continue
            selected = workspace
            break
    selected = selected or workspaces[0]

    try:
        store = load_json(_standby_path(standby_path))
    except (OSError, ValueError):
        store = {}
    captures = store.get("captures") if isinstance(store, Mapping) else None
    if isinstance(captures, list):
        selected_path = _canonical_path(selected)
        for capture in reversed(captures):
            workspace_value = capture.get("workspace_path") if isinstance(capture, Mapping) else None
            if (
                isinstance(workspace_value, str)
                and _canonical_path(Path(workspace_value)) == selected_path
                and capture.get("status") == "active"
                and isinstance(capture.get("reference"), str)
            ):
                return dict(capture)
    return _workspace_capture(selected, status="active")


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


def _pid_running(pid: object) -> bool:
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _workspace_catalog(
    selected_ref: str, *, root: Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Overlay Play captures on workspaces that currently exist in Rote."""

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

    tutorial = ensure_tutorial(root=root)
    summaries: list[dict[str, Any]] = [
        {
            "id": TUTORIAL_WORKSPACE_ID,
            "intent": "Start Here · learn the Journey world",
            "workspace": "start-here",
            "workspace_path": None,
            "created_at": "2026-08-20T16:00:00Z",
            "capture_state": "tutorial",
            "journey_mode": "tutorial",
            "live": False,
            "activity_epoch": None,
            "active_recently": False,
            "selected": selected_ref == TUTORIAL_REFERENCE,
            "workspace_available": True,
            "evidence_available": True,
            "graph_ready": True,
            "projectable": False,
            "tutorial": True,
            "nodes": len(tutorial.get("nodes", [])),
            "edges": len(tutorial.get("edges", [])),
            "commands": int(tutorial.get("telemetry", {}).get("commands") or 0),
        }
    ]
    lookup: dict[str, str] = {TUTORIAL_WORKSPACE_ID: TUTORIAL_REFERENCE}
    for workspace_path in _rote_workspaces():
        capture = captures_by_workspace.get(_canonical_path(workspace_path))
        evidence_available = (workspace_path / ".rote" / "workspace.db").is_file()
        activity_epoch, active_recently = _workspace_activity(workspace_path)
        if capture is None:
            workspace_capture = _workspace_capture(workspace_path)
            reference = str(workspace_capture["reference"])
            attached = reference == selected_ref
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
                    "capture_state": "active" if attached else "workspace",
                    "journey_mode": "live" if attached else "workspace",
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
        capture_state = str(capture.get("status") or "unknown")
        summaries.append(
            {
                "id": workspace_id,
                "intent": str(capture.get("intent") or "Untitled exploration"),
                "workspace": str(capture.get("workspace") or workspace_path.name),
                "workspace_path": str(workspace_path),
                "created_at": capture.get("created_at"),
                "capture_state": capture_state,
                "journey_mode": _journey_mode(capture_state),
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
                "journey_mode": "recorded",
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
    usable = next(
        (item for item in workspaces if item.get("graph_ready") and not item.get("tutorial")),
        None,
    )
    if usable is None:
        usable = next(
            (item for item in workspaces if item.get("projectable") and not item.get("tutorial")),
            None,
        )
    if usable is None:
        usable = next((item for item in workspaces if item.get("graph_ready")), None)
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
            "current_workspaces": sum(1 for item in refreshed if not item.get("tutorial")),
            "mapped_captures": sum(
                1
                for item in refreshed
                if item.get("workspace_available")
                and not item.get("tutorial")
                and item.get("capture_state") != "workspace"
            ),
            "stale_captures_hidden": stale,
            "projectors_scheduled": scheduled,
        },
    }
