"""Deterministic recorded workspace that teaches the Journey world model."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .journey import (
    _journey_key,
    _persist_graph_state,
    _snapshot_path,
    build_graph,
    load_graph,
    materialize_snapshot,
    normalize_entries,
)
from .private_store import atomic_write_json


TUTORIAL_REFERENCE = "tutorial:start-here-v1"
TUTORIAL_WORKSPACE_ID = _journey_key(TUTORIAL_REFERENCE)
TUTORIAL_VERSION = "start-here-v2"
TUTORIAL_ASSET_ROOT = Path(__file__).with_name("journey_tutorial")


def _row(sequence: int, command_type: str, params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "command_type": command_type,
        "params": json.dumps({"command": command_type, "params": dict(params)}),
        "response_ids": json.dumps([sequence]),
        "timestamp": f"2026-08-20T16:00:{sequence * 3:02d}.000Z",
        "skip_export": False,
    }


def _entries() -> list[dict[str, Any]]:
    return [
        _row(1, "InitSession", {"endpoint": "adapter/example"}),
        _row(
            2,
            "HttpRequest",
            {
                "endpoint": "adapter/example",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "example_call",
                        "arguments": {
                            "tool_name": "adapter.auth.ensure",
                            "arguments": {},
                        },
                    },
                },
            },
        ),
        _row(
            3,
            "HttpRequest",
            {
                "endpoint": "adapter/example",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "example_call",
                        "arguments": {"tool_name": "records.list", "arguments": {}},
                    },
                },
            },
        ),
        _row(
            4,
            "HttpRequest",
            {
                "endpoint": "adapter/example",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "example_call",
                        "arguments": {"tool_name": "records.update", "arguments": {}},
                    },
                },
            },
        ),
        _row(
            5,
            "HttpRequest",
            {
                "endpoint": "adapter/example",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "example_call",
                        "arguments": {"tool_name": "records.update", "arguments": {}},
                    },
                },
            },
        ),
        _row(
            6,
            "ProcessExec",
            {"invocation": {"program": "rg", "args": ["--files"]}},
        ),
        _row(7, "InitSession", {"endpoint": "stdio:/browser"}),
        _row(
            8,
            "HttpRequest",
            {
                "endpoint": "stdio:/browser",
                "body": {"method": "tools/call", "params": {"name": "browser_navigate"}},
            },
        ),
        _row(9, "QueryExtract", {"source_response": 8, "query": ".title"}),
        _row(10, "ComposeEmail", {"source_response": 9}),
    ]


def _tool_contract(_adapter_id: str, operation: str) -> Mapping[str, Any] | None:
    if operation == "adapter.auth.ensure":
        return {"method": "POST", "hints": {"readOnlyHint": False}}
    if operation == "records.list":
        return {"method": "GET", "hints": {"readOnlyHint": True}}
    if operation == "records.update":
        return {"method": "POST", "hints": {"readOnlyHint": False, "destructiveHint": False}}
    return None


def _metadata(sequence: int) -> dict[str, Any]:
    process_policy = (
        {"risk_tags": ["read_fs"]} if sequence == 6 else None
    )
    value: dict[str, Any] = {
        "ok": sequence != 4,
        "duration_ms": (80, 240, 760, 430, 520, 110, 90, 1250, 35, 180)[sequence - 1],
        "tokens": (0, 40, 920, 360, 440, 150, 0, 680, 120, 410)[sequence - 1],
    }
    if process_policy is not None:
        value["process_policy"] = process_policy
    return value


def ensure_tutorial(*, root: Path | None = None) -> dict[str, Any]:
    """Materialize the packaged tutorial through the production projector."""

    existing = load_graph(TUTORIAL_REFERENCE, root=root)
    existing_origin = existing.get("origin") if isinstance(existing, Mapping) else None
    if (
        isinstance(existing, Mapping)
        and isinstance(existing_origin, Mapping)
        and existing_origin.get("kind") == "tutorial"
        and existing_origin.get("exact_reference") == TUTORIAL_REFERENCE
        and existing_origin.get("recording_version") == TUTORIAL_VERSION
    ):
        return dict(existing)
    entries = _entries()
    activities = normalize_entries(
        entries,
        response_metadata={sequence: _metadata(sequence) for sequence in range(1, 11)},
        manifest_resolver=lambda adapter_id: {
            "name": "Example service" if adapter_id == "example" else adapter_id,
            "transport": "http",
        },
        tool_resolver=_tool_contract,
    )
    capture = {
        "reference": TUTORIAL_REFERENCE,
        "intent": "Learn how an agent journey becomes a world",
        "status": "recorded",
        "origin": {
            "kind": "tutorial",
            "exact_reference": TUTORIAL_REFERENCE,
            "source": "packaged_recording",
            "recording_version": TUTORIAL_VERSION,
        },
    }
    graph = build_graph(
        capture,
        activities=activities,
        dependencies=[],
        stats={"commands": len(activities), "responses": len(activities)},
    )
    graph["intent"]["source"] = "tutorial"
    graph["route"] = {
        "mode": "tutorial",
        "exploration_skipped": True,
        "label": "Start Here · deterministic recorded journey",
    }
    graph["state"] = "recorded"
    graph["updated_at"] = "2026-08-20T16:01:00Z"
    if graph.get("nodes"):
        graph["current_node"] = graph["nodes"][-1]["id"]
    _persist_graph_state(
        TUTORIAL_REFERENCE,
        fingerprint=TUTORIAL_VERSION,
        command_count=len(activities),
        response_count=len(activities),
        activities=activities,
        dependencies=[],
        graph=graph,
        reset_sources=True,
        root=root,
    )
    atomic_write_json(_snapshot_path(TUTORIAL_REFERENCE, root=root), materialize_snapshot(graph))
    return graph


def tutorial_exchange(sequence: int) -> dict[str, Any] | None:
    labels = {
        1: ("Initialize an adapter session", "Example service is equipped and ready."),
        2: ("Ensure authorization", "Required authority is satisfied before use."),
        3: ("Read records through the adapter", "Typed service evidence is returned."),
        4: ("Attempt a typed update", "The typed operation fails and becomes a visible blocker."),
        5: ("Retry the corrected update", "The corrected operation succeeds and bridges the route."),
        6: ("Inspect local files through proc", "The shell capability returns file evidence."),
        7: ("Initialize a browser lease", "A page session is equipped and ready."),
        8: ("Navigate through the browser", "The page ledger records the observed destination."),
        9: ("Extract from stored browser evidence", "A browser lens reads the cached title."),
        10: ("Compose a durable artifact", "Verified evidence becomes a user-facing result."),
    }
    pair = labels.get(sequence)
    if pair is None:
        return None
    return {
        "schema": "play.journey-exchange/v1",
        "sequence": sequence,
        "request": {"tutorial_step": pair[0], "payload": "[DEMONSTRATION ONLY]"},
        "response": {"summary": pair[1], "ok": sequence != 4},
        "truncated": False,
    }


def tutorial_payload() -> dict[str, Any]:
    value = json.loads((TUTORIAL_ASSET_ROOT / "cues.json").read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, Mapping) else {}
