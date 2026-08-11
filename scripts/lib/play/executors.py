"""Closed executor classification for compiled Play actions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RUNTIME_COMMANDLESS_ACTIONS = frozenset(
    {
        "present_awareness_digest",
        "present_play_management",
        "present_search_results",
        "build_receipt",
        "classify_adequacy",
        "route_inspected_play",
        "verify_play_output",
    }
)


def action_executor(action_id: str, action: Mapping[str, Any]) -> str | None:
    """Return the only executor allowed to own an action, or None if unclosed."""

    kind = action.get("kind")
    command = action.get("command")
    if kind == "deterministic":
        if command is None:
            return "runtime" if action_id in RUNTIME_COMMANDLESS_ACTIONS else None
        if isinstance(command, str) and command.startswith("scripts/bin/"):
            return "runtime"
        return None
    if kind == "delegated":
        return "specialist" if command is None else None
    if kind == "evaluator":
        return "model" if command is None else None
    return None
