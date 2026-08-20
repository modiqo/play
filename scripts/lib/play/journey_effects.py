"""Typed effect posture for Rote Journey activities.

This module deliberately consumes Rote's persisted contracts instead of
guessing from friendly operation or executable names.  It runs only in the
asynchronous Journey projector.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


SCHEMA = "play.journey-effect/v1"

_READ_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
_WRITE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_BROWSER_READ_PRIMITIVES = {"inventory", "ledger", "slice", "lens", "wait", "navigate"}
_PROCESS_WRITE_TAGS = {
    "write_fs",
    "write_outside_workspace",
    "package_install",
    "global_install",
    "process_control",
    "destructive",
    "privilege_escalation",
}
_PROCESS_UNCERTAIN_TAGS = {"network", "unknown_side_effects"}


def _rote_home() -> Path:
    override = os.environ.get("ROTE_HOME")
    return Path(override) if override else Path.home() / ".rote"


def _profile(
    posture: str,
    *,
    scopes: Sequence[str],
    source: str,
    confidence: str = "deterministic",
    destructive: bool | None = None,
    risk_tags: Sequence[str] = (),
    methods: Sequence[str] = (),
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "posture": posture,
        "scopes": sorted(set(scopes)),
        "source": source,
        "confidence": confidence,
        "destructive": destructive,
    }
    if risk_tags:
        value["risk_tags"] = sorted(set(risk_tags))
    if methods:
        value["methods"] = list(dict.fromkeys(methods))
    return value


@lru_cache(maxsize=32)
def _adapter_tool_index(adapter_id: str) -> dict[str, Mapping[str, Any]]:
    """Load one installed adapter's typed tool index once per worker."""

    if not adapter_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
        for character in adapter_id
    ):
        return {}
    path = _rote_home() / "adapters" / adapter_id / "tools.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(value, Mapping):
        candidates = value.get("tools")
    else:
        candidates = value
    if not isinstance(candidates, list):
        return {}
    return {
        str(item["name"]): item
        for item in candidates
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }


def adapter_tool_contract(adapter_id: str, operation: str) -> Mapping[str, Any] | None:
    return _adapter_tool_index(adapter_id).get(operation)


def _boolean_hint(hints: Mapping[str, Any], camel: str, snake: str) -> bool | None:
    value = hints.get(camel, hints.get(snake))
    return value if isinstance(value, bool) else None


def _adapter_operation_profile(contract: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(contract, Mapping):
        return _profile(
            "unknown",
            scopes=("external_service",),
            source="adapter_tool_missing",
            confidence="unknown",
        )
    method = str(contract.get("method") or "").upper()
    hints = contract.get("hints")
    hints = hints if isinstance(hints, Mapping) else {}
    read_only = _boolean_hint(hints, "readOnlyHint", "read_only_hint")
    destructive = _boolean_hint(hints, "destructiveHint", "destructive_hint")
    if read_only is True:
        posture = "read"
        destructive = False if destructive is None else destructive
        source = "adapter_tool_hint"
    elif read_only is False:
        posture = "write"
        source = "adapter_tool_hint"
    elif method in _READ_HTTP_METHODS:
        posture = "read"
        destructive = False
        source = "adapter_http_method"
    elif method in _WRITE_HTTP_METHODS:
        posture = "write"
        destructive = method == "DELETE" if destructive is None else destructive
        source = "adapter_http_method"
    else:
        posture = "unknown"
        source = "adapter_hint_absent"
    return _profile(
        posture,
        scopes=("external_service",),
        source=source,
        confidence="deterministic" if posture != "unknown" else "unknown",
        destructive=destructive,
        methods=(method,) if method else (),
    )


def _aggregate_adapter_profiles(profiles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not profiles:
        return _profile(
            "unknown",
            scopes=("external_service",),
            source="adapter_tool_missing",
            confidence="unknown",
        )
    postures = {str(item.get("posture") or "unknown") for item in profiles}
    if "unknown" in postures:
        posture = "unknown"
    elif postures == {"read"}:
        posture = "read"
    elif postures == {"write"}:
        posture = "write"
    else:
        posture = "mixed"
    destructive_values = [item.get("destructive") for item in profiles]
    if True in destructive_values:
        destructive = True
    elif all(value is False for value in destructive_values):
        destructive = False
    else:
        destructive = None
    return _profile(
        posture,
        scopes=tuple(
            str(scope)
            for item in profiles
            for scope in item.get("scopes", [])
            if isinstance(scope, str)
        ),
        source="adapter_tool_contract",
        confidence="deterministic" if posture != "unknown" else "unknown",
        destructive=destructive,
        methods=tuple(
            str(method)
            for item in profiles
            for method in item.get("methods", [])
            if isinstance(method, str)
        ),
    )


def _process_profile(
    payload: Mapping[str, Any],
    typed_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    policy: Mapping[str, Any] = {}
    for receipt in typed_receipts:
        candidate = receipt.get("process_policy")
        if isinstance(candidate, Mapping):
            policy = candidate
            break
    if not policy:
        candidate = payload.get("policy")
        policy = candidate if isinstance(candidate, Mapping) else {}
    raw_tags = policy.get("risk_tags")
    tags = (
        {
            str(tag).lower()
            for tag in raw_tags
            if isinstance(tag, str)
        }
        if isinstance(raw_tags, list)
        else set()
    )
    has_read = "read_fs" in tags
    has_write = bool(tags & _PROCESS_WRITE_TAGS)
    uncertain = bool(tags & _PROCESS_UNCERTAIN_TAGS)
    if uncertain:
        posture = "unknown"
    elif has_read and has_write:
        posture = "mixed"
    elif has_write:
        posture = "write"
    elif has_read:
        posture = "read"
    else:
        posture = "unknown"
    scopes: set[str] = set()
    if has_read:
        scopes.add("local_fs")
    if "write_fs" in tags:
        scopes.add("local_fs")
    if "write_outside_workspace" in tags:
        scopes.add("host_fs")
    if "network" in tags:
        scopes.add("external_service")
    if tags & {"process_control", "background_process", "pty"}:
        scopes.add("process")
    return _profile(
        posture,
        scopes=tuple(scopes or {"process"}),
        source="process_policy" if policy else "process_policy_missing",
        confidence="deterministic" if posture != "unknown" else "unknown",
        destructive=True if "destructive" in tags else False if tags else None,
        risk_tags=tuple(tags),
    )


def classify_effect(
    command_type: str,
    payload: Mapping[str, Any],
    capability: Mapping[str, Any],
    *,
    tool_resolver: Callable[[str, str], Mapping[str, Any] | None] | None = None,
    typed_receipts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return a safe read/write posture from typed Rote records."""

    family = str(capability.get("family") or "")
    if family == "adapter":
        if command_type == "DataQuery":
            return _profile("read", scopes=("local_data",), source="data_query")
        phase = str(capability.get("phase") or "")
        if phase == "probe":
            return _profile("read", scopes=("external_service",), source="adapter_probe")
        if command_type == "For" and capability.get("id") == "http":
            method = str(capability.get("http_method") or "").upper()
            return _adapter_operation_profile({"method": method})
        adapter_id = str(capability.get("id") or "")
        operations = capability.get("operations")
        operations = operations if isinstance(operations, list) else []
        resolver = tool_resolver or adapter_tool_contract
        return _aggregate_adapter_profiles(
            [
                _adapter_operation_profile(resolver(adapter_id, operation))
                for operation in operations
                if isinstance(operation, str)
            ]
        )
    if family == "proc":
        return _process_profile(payload, typed_receipts)
    if family == "browser":
        primitive = str(capability.get("primitive") or "")
        if primitive in _BROWSER_READ_PRIMITIVES:
            scopes = ("external_service", "browser_state") if primitive == "navigate" else ("browser_state",)
            return _profile("read", scopes=scopes, source="browser_ledger_primitive")
        return _profile(
            "unknown",
            scopes=("external_service", "browser_state"),
            source="browser_action_without_effect_receipt",
            confidence="unknown",
        )
    if command_type in {"QueryRead", "QueryExtract", "Display", "DepsCheck"}:
        return _profile("read", scopes=("workspace",), source="workspace_command")
    if command_type in {"SetVariable", "ComposeEmail"}:
        return _profile("write", scopes=("workspace",), source="workspace_command", destructive=False)
    return _profile("unknown", scopes=("workspace",), source="typed_record_unavailable", confidence="unknown")
