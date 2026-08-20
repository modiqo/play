"""Owner-private evidence projections for the Journey viewer."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .journey import _capture, _load_source
from .journey_capabilities import capability_descriptor
from .journey_world_model import enrich_operation
from .journey_view_catalog import _workspace_capture_for_reference


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
                # Preserve semantic labels for journeys projected before rules-v3.
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
            operation_context = dict(activity)
            operation_context["capability"] = capability
            enrich_operation(operation_context)
            interactions.append(
                {
                    "sequence": sequence,
                    "command_type": command_type,
                    "operation": operation,
                    "provider": provider,
                    "capability": dict(capability),
                    "capability_ref": operation_context.get("capability_ref")
                    if isinstance(operation_context.get("capability_ref"), str)
                    else None,
                    "modality": operation_context.get("modality")
                    if isinstance(operation_context.get("modality"), str)
                    else None,
                    "lifecycle_phase": operation_context.get("lifecycle_phase")
                    if isinstance(operation_context.get("lifecycle_phase"), str)
                    else "use",
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
                    "semantic_kind": str(
                        activity.get("semantic_kind") or activity.get("kind") or "phase"
                    ),
                    "semantic_role": activity.get("role")
                    if isinstance(activity.get("role"), str)
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
    if capture is None:
        capture = _workspace_capture_for_reference(capture_ref)
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
