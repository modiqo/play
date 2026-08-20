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
TUTORIAL_VERSION = "start-here-v3"
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
        _row(1, "SetVariable", {"name": "route", "value": "notion-adapter"}),
        _row(2, "InitSession", {"endpoint": "adapter/notion"}),
        _row(
            3,
            "HttpRequest",
            {
                "endpoint": "adapter/notion",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "notion_call",
                        "arguments": {
                            "tool_name": "adapter.auth.ensure",
                            "arguments": {},
                        },
                    },
                },
            },
        ),
        _row(
            4,
            "HttpRequest",
            {
                "endpoint": "adapter/notion",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "notion_call",
                        "arguments": {"tool_name": "databases.query", "arguments": {}},
                    },
                },
            },
        ),
        _row(
            5,
            "HttpRequest",
            {
                "endpoint": "adapter/notion",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "notion_call",
                        "arguments": {"tool_name": "pages.create", "arguments": {}},
                    },
                },
            },
        ),
        _row(
            6,
            "HttpRequest",
            {
                "endpoint": "adapter/notion",
                "body": {
                    "method": "tools/call",
                    "params": {
                        "name": "notion_call",
                        "arguments": {"tool_name": "pages.create", "arguments": {}},
                    },
                },
            },
        ),
        _row(
            7,
            "ProcessExec",
            {"invocation": {"program": "notion-cli", "args": ["validate"]}},
        ),
        _row(8, "InitSession", {"endpoint": "stdio:/browser"}),
        _row(
            9,
            "HttpRequest",
            {
                "endpoint": "stdio:/browser",
                "body": {"method": "tools/call", "params": {"name": "browser_navigate"}},
            },
        ),
        _row(10, "QueryExtract", {"source_response": 9, "query": ".title"}),
        _row(11, "ComposeEmail", {"source_response": 10}),
    ]


def _tool_contract(_adapter_id: str, operation: str) -> Mapping[str, Any] | None:
    if operation == "adapter.auth.ensure":
        return {"method": "POST", "hints": {"readOnlyHint": False}}
    if operation == "databases.query":
        return {"method": "GET", "hints": {"readOnlyHint": True}}
    if operation == "pages.create":
        return {"method": "POST", "hints": {"readOnlyHint": False, "destructiveHint": False}}
    return None


def _metadata(sequence: int) -> dict[str, Any]:
    process_policy = (
        {"risk_tags": ["read_fs"]} if sequence == 7 else None
    )
    value: dict[str, Any] = {
        "ok": sequence != 5,
        "duration_ms": (30, 80, 240, 760, 430, 520, 110, 90, 1250, 35, 180)[sequence - 1],
        "tokens": (20, 0, 40, 920, 360, 440, 150, 0, 680, 120, 410)[sequence - 1],
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
        response_metadata={sequence: _metadata(sequence) for sequence in range(1, 12)},
        manifest_resolver=lambda adapter_id: {
            "name": "Notion" if adapter_id == "notion" else adapter_id,
            "transport": "http",
        },
        tool_resolver=_tool_contract,
    )
    for activity in activities:
        if activity.get("command_type") == "SetVariable":
            activity["operation"] = "Choose Notion access route"
        if activity.get("command_type") == "InitSession":
            capability = activity.get("capability")
            capability = capability if isinstance(capability, Mapping) else {}
            if capability.get("family") == "adapter":
                activity["provider"] = "notion"
                activity["operation"] = "Initialize Notion adapter"
            elif capability.get("family") == "browser":
                activity["provider"] = "browser"
                activity["operation"] = "Initialize browser session"
    capture = {
        "reference": TUTORIAL_REFERENCE,
        "intent": "Create a page in Notion and verify it",
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
        1: ("Choose a Notion access route", "The mixed-modality route will use CALL, SHELL, and DRIVE."),
        2: ("Initialize the Notion adapter", "The Notion CALL capability is equipped and ready."),
        3: ("Ensure Notion authorization", "Required Notion authority is satisfied before use."),
        4: ("Query the target database", "Typed Notion database evidence is returned."),
        5: ("Attempt to create the page", "Missing database access becomes a visible blocker."),
        6: ("Retry page creation", "The corrected Notion operation succeeds and bridges the route."),
        7: ("Validate content with notion-cli", "The SHELL capability returns local validation evidence."),
        8: ("Initialize a browser lease", "The DRIVE page session is equipped and ready."),
        9: ("Open the new Notion page", "The browser ledger records the observed destination."),
        10: ("Read stored browser evidence", "A browser lens verifies the Notion page title."),
        11: ("Compose the delivery artifact", "The verified Notion page becomes a user-facing result."),
    }
    pair = labels.get(sequence)
    if pair is None:
        return None
    return {
        "schema": "play.journey-exchange/v1",
        "sequence": sequence,
        "request": {"tutorial_step": pair[0], "payload": "[DEMONSTRATION ONLY]"},
        "response": {"summary": pair[1], "ok": sequence != 5},
        "truncated": False,
    }


def tutorial_payload() -> dict[str, Any]:
    value = json.loads((TUTORIAL_ASSET_ROOT / "cues.json").read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, Mapping) else {}
