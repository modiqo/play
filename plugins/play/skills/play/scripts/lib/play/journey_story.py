"""Deterministic human journey projection over the complete evidence graph."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any


SCHEMA = "play.journey-story/v1"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _title(node: Mapping[str, Any], *, effect_seen: bool) -> str:
    kind = str(node.get("kind") or "phase")
    label = str(node.get("label") or "Continue the journey")
    lower = label.lower()
    provider = node.get("provider")
    if kind == "intent":
        return "Requested outcome"
    if kind == "decision":
        return label
    if kind == "authority":
        return f"Authorize {provider}" if provider else "Approve access"
    if kind == "capability":
        if provider:
            return f"Connect {provider}"
        if "git" in lower:
            return "Prepare repository access"
        if "sh -c" in lower or "process" in lower:
            return "Prepare local execution"
        return "Check the completed work" if effect_seen else "Prepare the execution path"
    if kind == "effect":
        if "git" in lower:
            return "Apply repository changes"
        if provider:
            return f"Run {provider} operation"
        return "Execute the approved change"
    if kind == "evidence":
        return "Verify the completed work" if effect_seen else "Inspect the current state"
    if kind == "phase":
        if "git" in lower:
            return "Confirm repository state" if effect_seen else "Inspect repository state"
        if "curl" in lower:
            return "Verify the deployed surface" if effect_seen else "Inspect the remote surface"
        if "just" in lower or "pytest" in lower or "test" in lower:
            return "Run project checks"
        if "node" in lower or "jq" in lower:
            return "Transform the working data"
        if "streamfollow" in lower or lower == "process":
            return "Wait for running work"
        if "inspect relevant source" in lower:
            return "Review the completed output" if effect_seen else "Inspect source and context"
        return label if label and label != "Continue the journey" else ("Confirm completion" if effect_seen else "Prepare the work")
    if kind == "blocker":
        return label if lower.startswith("blocked") else f"Blocked: {label}"
    if kind == "recovery":
        return label if lower.startswith("recover") else f"Recover: {label}"
    if kind == "milestone":
        return label
    if kind == "artifact":
        return f"Produce {label}"
    if kind == "play_candidate":
        return "Shape a reusable Play"
    if kind == "play":
        return "Publish the Play"
    return label


def build_story(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Create a readable causal spine without deleting any underlying evidence."""

    if graph.get("schema") != "play.journey-graph/v1":
        raise ValueError("Journey story requires play.journey-graph/v1")
    raw_nodes = [dict(node) for node in graph.get("nodes", []) if isinstance(node, Mapping)]
    if not raw_nodes:
        raise ValueError("Journey graph has no nodes")
    ordered = sorted(
        raw_nodes,
        key=lambda node: (
            -1 if node.get("kind") == "intent" else int(node.get("first_sequence") or 10**9),
            {"capability": 0, "authority": 1}.get(str(node.get("kind") or ""), 2),
            str(node.get("id") or ""),
        ),
    )
    chapters: list[dict[str, Any]] = []
    effect_seen = False
    lane_y = {
        "intent": 0.0, "decision": -10.0, "capability": -7.0, "authority": -4.0,
        "phase": -1.0, "effect": 2.0, "evidence": 7.0, "artifact": 10.0,
        "blocker": -11.0, "recovery": -8.0, "milestone": 6.0,
        "learning": 9.0, "play_candidate": 2.0, "play": 2.0,
    }
    for order, node in enumerate(ordered):
        kind = str(node.get("kind") or "phase")
        telemetry_value = node.get("telemetry")
        telemetry: Mapping[str, Any] = (
            telemetry_value if isinstance(telemetry_value, Mapping) else {}
        )
        evidence_value = node.get("evidence")
        evidence: Mapping[str, Any] = (
            evidence_value if isinstance(evidence_value, Mapping) else {}
        )
        duration = int(telemetry.get("duration_ms") or 0)
        chapter = {
            "id": str(node.get("id") or f"chapter_{order}"),
            "order": order,
            "kind": kind,
            "title": _title(node, effect_seen=effect_seen),
            "detail": str(node.get("label") or ""),
            "status": str(node.get("status") or "planned"),
            "provider": node.get("provider") if isinstance(node.get("provider"), str) else None,
            "effect": node.get("effect") if isinstance(node.get("effect"), str) else None,
            "position": {
                "x": float(order * 8),
                "y": lane_y.get(kind, 0.0),
                "z": round(min(4.5, math.log2(max(1, duration + 1)) / 3), 3),
            },
            "activity_count": int(node.get("activity_count") or 0),
            "capability_refs": [
                str(value)
                for value in node.get("capability_refs", [])
                if isinstance(value, str)
            ],
            "modalities": [
                str(value)
                for value in node.get("modalities", [])
                if isinstance(value, str)
            ],
            "lifecycle_phases": [
                str(value)
                for value in node.get("lifecycle_phases", [])
                if isinstance(value, str)
            ],
            "telemetry": {
                "duration_ms": duration,
                "payload_tokens": int(telemetry.get("payload_tokens") or 0),
                "tokens_saved": int(telemetry.get("tokens_saved") or 0),
            },
            "evidence": dict(evidence),
        }
        chapters.append(chapter)
        effect_seen = effect_seen or kind == "effect"

    routes = [
        {
            "id": f"route_{index:04d}",
            "source": source["id"],
            "target": target["id"],
            "kind": "traverses",
            "label": "then",
        }
        for index, (source, target) in enumerate(zip(chapters, chapters[1:]), 1)
    ]
    intent_value = graph.get("intent")
    intent: Mapping[str, Any] = (
        intent_value if isinstance(intent_value, Mapping) else {}
    )
    graph_telemetry_value = graph.get("telemetry")
    graph_telemetry: Mapping[str, Any] = (
        graph_telemetry_value
        if isinstance(graph_telemetry_value, Mapping)
        else {}
    )
    edge_values = graph.get("edges")
    edges = edge_values if isinstance(edge_values, list) else []
    origin_value = graph.get("origin")
    origin = dict(origin_value) if isinstance(origin_value, Mapping) else {}
    route_value = graph.get("route")
    route = dict(route_value) if isinstance(route_value, Mapping) else {
        "mode": "exploration",
        "exploration_skipped": False,
        "label": "Exploration · route formed during the work",
    }
    benefit_value = graph.get("benefit")
    benefit = dict(benefit_value) if isinstance(benefit_value, Mapping) else {
        "workflow_discovery_avoided": False,
        "capability_discovery_avoided": False,
        "typed_provider_operations": 0,
    }
    capabilities = [
        dict(value)
        for value in graph.get("capabilities", [])
        if isinstance(value, Mapping)
    ]
    story = {
        "schema": SCHEMA,
        "journey_key": str(graph.get("journey_key") or ""),
        "graph_generation": int(graph.get("generation") or 1),
        "state": str(graph.get("state") or "active"),
        "outcome": str(intent.get("label") or "Captured exploration"),
        "origin": origin,
        "route": route,
        "benefit": benefit,
        "capabilities": capabilities,
        "chapters": chapters,
        "routes": routes,
        "current_chapter": str(graph.get("current_node") or chapters[-1]["id"]),
        "telemetry": dict(graph_telemetry),
        "audit": {
            "canonical_nodes": len(raw_nodes),
            "canonical_edges": len([edge for edge in edges if isinstance(edge, Mapping)]),
            "canonical_capabilities": len(capabilities),
            "preserved_chapter_ids": [chapter["id"] for chapter in chapters],
        },
        "updated_at": str(graph.get("updated_at") or ""),
    }
    story["story_sha256"] = "sha256:" + hashlib.sha256(_canonical(story).encode()).hexdigest()
    return story
