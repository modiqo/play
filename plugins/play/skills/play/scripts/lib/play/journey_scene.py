"""Deterministic isometric scene projection for complete Play Journey graphs."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA = "play.journey-scene/v1"
PROJECTION = "2:1-dimetric"
TILE_WIDTH = 48
TILE_HEIGHT = 24
HEIGHT_UNIT = 14
NODE_PITCH = 3.5
LANE_PITCH = 4.0

LANES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("intent", "Intent and decisions", ("intent", "decision")),
    ("capability", "Capabilities", ("capability",)),
    ("authority", "Authority", ("authority",)),
    ("work", "Work and effects", ("phase", "effect")),
    ("evidence", "Evidence and artifacts", ("evidence", "artifact")),
    ("recovery", "Blockers and recovery", ("blocker", "recovery")),
    ("milestone", "Milestones and learning", ("milestone", "learning")),
    ("play", "Reusable Plays", ("play_candidate", "play")),
)

NODE_CODES = {
    "intent": "IN",
    "phase": "PH",
    "capability": "CP",
    "decision": "DC",
    "authority": "AU",
    "effect": "FX",
    "evidence": "EV",
    "artifact": "AR",
    "blocker": "BL",
    "recovery": "RC",
    "milestone": "MS",
    "learning": "LN",
    "play_candidate": "PC",
    "play": "PL",
}

EDGE_OFFSETS = {
    "decomposes_into": -0.30,
    "derived_from": -0.15,
    "requires": -0.10,
    "selects": 0.0,
    "authorizes": 0.05,
    "executes": 0.10,
    "produces": 0.15,
    "verifies": 0.20,
    "blocked_by": 0.25,
    "recovers": 0.30,
    "refines": 0.35,
    "crystallizes_into": 0.40,
}


class JourneySceneError(RuntimeError):
    """A graph could not be projected into a safe deterministic scene."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _scene_id(parts: Sequence[object]) -> str:
    return "scene_" + hashlib.sha256(_canonical(list(parts)).encode()).hexdigest()[:20]


def _lane_for(kind: str) -> tuple[int, str]:
    for index, (lane_id, _label, kinds) in enumerate(LANES):
        if kind in kinds:
            return index, lane_id
    return 3, "work"


def _height(activity_count: int) -> int:
    return max(1, min(6, 1 + int(math.log2(max(1, activity_count)))))


def _footprint(kind: str, activity_count: int) -> dict[str, float]:
    if kind == "intent":
        return {"w": 3.0, "d": 3.0}
    if kind in {"decision", "blocker", "recovery"}:
        return {"w": 2.5, "d": 2.5}
    if kind in {"evidence", "artifact", "play_candidate", "play"}:
        return {"w": 3.0, "d": 2.0}
    if activity_count >= 8:
        return {"w": 3.0, "d": 2.0}
    return {"w": 2.0, "d": 2.0}


def _point(gx: float, gy: float, z: float = 0.0) -> dict[str, float]:
    return {"gx": round(gx, 3), "gy": round(gy, 3), "z": round(z, 3)}


def _edge_route(
    source: Mapping[str, Any], target: Mapping[str, Any], kind: str
) -> list[dict[str, float]]:
    source_position = source["position"]
    target_position = target["position"]
    source_footprint = source["footprint"]
    target_footprint = target["footprint"]
    sx = float(source_position["gx"]) + float(source_footprint["w"]) / 2
    sy = float(source_position["gy"]) + float(source_footprint["d"]) / 2
    tx = float(target_position["gx"]) + float(target_footprint["w"]) / 2
    ty = float(target_position["gy"]) + float(target_footprint["d"]) / 2
    offset = EDGE_OFFSETS.get(kind, 0.0)
    if abs(sx - tx) < 0.001 or abs(sy - ty) < 0.001:
        return [_point(sx, sy, 0.1 + offset), _point(tx, ty, 0.1 + offset)]
    elbow_x = tx
    elbow_y = sy + offset
    return [
        _point(sx, sy, 0.1 + offset),
        _point(elbow_x, elbow_y, 0.1 + offset),
        _point(tx, ty, 0.1 + offset),
    ]


def _safe_evidence(value: object) -> dict[str, list[Any]]:
    expected = (
        "play_events",
        "rote_commands",
        "rote_responses",
        "receipt_refs",
        "artifact_refs",
    )
    source = value if isinstance(value, Mapping) else {}
    return {
        key: list(source.get(key, [])) if isinstance(source.get(key), list) else []
        for key in expected
    }


def build_scene(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Project every semantic node and edge into stable 2:1 dimetric geometry."""

    if graph.get("schema") != "play.journey-graph/v1":
        raise JourneySceneError("Journey scene requires play.journey-graph/v1")
    raw_nodes = [dict(value) for value in graph.get("nodes", []) if isinstance(value, Mapping)]
    raw_edges = [dict(value) for value in graph.get("edges", []) if isinstance(value, Mapping)]
    if not raw_nodes:
        raise JourneySceneError("Journey graph has no nodes")

    nodes: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    lane_members: dict[str, list[str]] = {lane_id: [] for lane_id, _label, _kinds in LANES}
    for order, raw in enumerate(raw_nodes):
        node_id = str(raw.get("id") or "")
        kind = str(raw.get("kind") or "phase")
        if not node_id or node_id in by_id:
            raise JourneySceneError("Journey graph contains a missing or duplicate node ID")
        lane_index, lane_id = _lane_for(kind)
        activity_count = int(raw.get("activity_count") or 0)
        footprint = _footprint(kind, activity_count)
        position = _point(order * NODE_PITCH, lane_index * LANE_PITCH)
        telemetry_value = raw.get("telemetry")
        telemetry = dict(telemetry_value) if isinstance(telemetry_value, Mapping) else {}
        node = {
            "id": node_id,
            "order": order,
            "code": NODE_CODES.get(kind, "PH"),
            "kind": kind,
            "label": str(raw.get("label") or kind),
            "status": str(raw.get("status") or "planned"),
            "provider": raw.get("provider") if isinstance(raw.get("provider"), str) else None,
            "effect": raw.get("effect") if isinstance(raw.get("effect"), str) else None,
            "lane": lane_id,
            "position": position,
            "footprint": footprint,
            "height": _height(activity_count),
            "activity_count": activity_count,
            "telemetry": {
                "duration_ms": int(telemetry.get("duration_ms") or 0),
                "payload_tokens": int(telemetry.get("payload_tokens") or 0),
                "tokens_saved": int(telemetry.get("tokens_saved") or 0),
            },
            "evidence": _safe_evidence(raw.get("evidence")),
        }
        nodes.append(node)
        by_id[node_id] = node
        lane_members[lane_id].append(node_id)

    edges: list[dict[str, Any]] = []
    for raw in raw_edges:
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        kind = str(raw.get("kind") or "derived_from")
        if source not in by_id or target not in by_id:
            raise JourneySceneError(f"Journey edge references an unknown node: {source} -> {target}")
        edges.append(
            {
                "id": _scene_id((source, target, kind)),
                "source": source,
                "target": target,
                "kind": kind,
                "route": _edge_route(by_id[source], by_id[target], kind),
                "active": target == graph.get("current_node"),
            }
        )

    districts = [
        {
            "id": lane_id,
            "label": label,
            "lane": lane_index,
            "node_ids": lane_members[lane_id],
        }
        for lane_index, (lane_id, label, _kinds) in enumerate(LANES)
        if lane_members[lane_id]
    ]
    max_gx = max(
        float(node["position"]["gx"]) + float(node["footprint"]["w"])
        for node in nodes
    )
    max_gy = max(
        float(node["position"]["gy"]) + float(node["footprint"]["d"])
        for node in nodes
    )
    intent_value = graph.get("intent")
    telemetry_value = graph.get("telemetry")
    scene = {
        "schema": SCHEMA,
        "graph_generation": int(graph.get("generation") or 1),
        "material_generation": int(graph.get("material_generation") or 0),
        "journey_key": str(graph.get("journey_key") or ""),
        "state": str(graph.get("state") or "active"),
        "intent": dict(intent_value) if isinstance(intent_value, Mapping) else {},
        "projection": {
            "kind": PROJECTION,
            "tile_width": TILE_WIDTH,
            "tile_height": TILE_HEIGHT,
            "height_unit": HEIGHT_UNIT,
        },
        "bounds": {"min_gx": 0.0, "min_gy": 0.0, "max_gx": max_gx, "max_gy": max_gy},
        "districts": districts,
        "nodes": nodes,
        "edges": edges,
        "current_node": str(graph.get("current_node") or "node_intent"),
        "telemetry": dict(telemetry_value) if isinstance(telemetry_value, Mapping) else {},
        "updated_at": str(graph.get("updated_at") or ""),
    }
    scene["scene_sha256"] = "sha256:" + hashlib.sha256(_canonical(scene).encode()).hexdigest()
    return scene
