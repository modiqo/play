"""Owner-private sidekick state: the save-hook standby store and preference ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .private_store import atomic_write_json, load_json
from .render import json_text
from .state_home import state_path


SCHEMA = "play.sidekick/v1"
STANDBY_SCHEMA = "play.standby/v1"
LEDGER_SCHEMA = "play.preferences/v1"
def _default_standby_path() -> Path:
    override = os.environ.get("PLAY_SIDEKICK_STANDBY_PATH")
    return Path(override) if override else state_path("standby.json")


def _default_ledger_path() -> Path:
    override = os.environ.get("PLAY_SIDEKICK_LEDGER_PATH")
    return (
        Path(override) if override else state_path("preferences.json")
    )
HOOK_TTL_SECONDS = 7 * 24 * 3600
MAX_HOOKS = 20
MAX_INTENT_CHARS = 400
POLICIES = ("intervene", "mention_only", "silent")
SCOPES = ("session", "project", "global")

_CLASS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "build-ship-chore",
        re.compile(
            r"\b(deploy|release|ship|publish|build|package|migrate|rollback|stage|staging)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data-fetch-report",
        re.compile(
            r"\b(retrieve|fetch|get|find|collect|download|export|list|summarize|report|compare|calculate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ops-maintenance",
        re.compile(
            r"\b(monitor|check|restart|rotate|backup|clean|audit|health|logs?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "creative-exploratory",
        re.compile(
            r"\b(prototype|design|sketch|animation|explore|experiment|vibe|style|layout)\b",
            re.IGNORECASE,
        ),
    ),
)


def coarse_task_class(text: str | None) -> str:
    """Map free intent text onto the closed coarse task-class set."""

    if not isinstance(text, str) or not text.strip():
        return "unclassified"
    for name, pattern in _CLASS_RULES:
        if pattern.search(text):
            return name
    return "unclassified"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_store(path: Path) -> Any:
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def load_ledger(path: Path | None = None) -> list[dict[str, Any]]:
    """Return the durable scoped preference entries, tolerating an absent store."""

    store = _read_store(path or _default_ledger_path())
    if not isinstance(store, Mapping) or store.get("schema") != LEDGER_SCHEMA:
        return []
    entries = store.get("entries")
    if not isinstance(entries, list):
        return []
    valid = []
    for entry in entries:
        if (
            isinstance(entry, Mapping)
            and entry.get("scope") in SCOPES
            and isinstance(entry.get("task_class"), str)
            and entry.get("policy") in POLICIES
        ):
            valid.append(dict(entry))
    return valid


def append_ledger_entry(
    *,
    statement: str,
    task_class: str,
    policy: str,
    scope: str = "global",
    path: Path | None = None,
) -> str:
    """Append one scoped preference entry and return its content reference."""

    if policy not in POLICIES:
        raise ValueError(f"unknown preference policy {policy!r}")
    if scope not in SCOPES:
        raise ValueError(f"unknown preference scope {scope!r}")
    target = path or _default_ledger_path()
    entries = load_ledger(target)
    entry = {
        "scope": scope,
        "task_class": task_class,
        "policy": policy,
        "statement": statement[:MAX_INTENT_CHARS],
        "recorded_at": _utc_now(),
    }
    entries = [
        existing
        for existing in entries
        if not (
            existing.get("scope") == scope
            and existing.get("task_class") == task_class
        )
    ]
    entries.append(entry)
    atomic_write_json(target, {"schema": LEDGER_SCHEMA, "entries": entries})
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _load_hooks(path: Path) -> list[dict[str, Any]]:
    store = _read_store(path)
    if not isinstance(store, Mapping) or store.get("schema") != STANDBY_SCHEMA:
        return []
    hooks = store.get("hooks")
    if not isinstance(hooks, list):
        return []
    fresh: list[dict[str, Any]] = []
    now = time.time()
    for hook in hooks:
        if not isinstance(hook, Mapping):
            continue
        armed_at = hook.get("armed_at_epoch")
        if isinstance(armed_at, (int, float)) and now - armed_at <= HOOK_TTL_SECONDS:
            fresh.append(dict(hook))
    return fresh


def arm_hook(
    *,
    intent: str,
    task_class: str,
    reason: str,
    path: Path | None = None,
) -> str:
    """Arm one save hook for an unserved outcome and return its content reference."""

    target = path or _default_standby_path()
    hooks = _load_hooks(target)
    hook = {
        "intent": intent[:MAX_INTENT_CHARS],
        "task_class": task_class,
        "reason": reason,
        "armed_at": _utc_now(),
        "armed_at_epoch": time.time(),
    }
    canonical = json.dumps(
        {key: hook[key] for key in ("intent", "task_class", "reason", "armed_at")},
        sort_keys=True,
        separators=(",", ":"),
    )
    hook_ref = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    hook["hook_ref"] = hook_ref
    hooks.append(hook)
    atomic_write_json(target, {"schema": STANDBY_SCHEMA, "hooks": hooks[-MAX_HOOKS:]})
    return hook_ref


def latest_hook(path: Path | None = None) -> dict[str, Any] | None:
    """Return the most recently armed unexpired save hook, if any."""

    hooks = _load_hooks(path or _default_standby_path())
    return hooks[-1] if hooks else None


def record_standby(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Handle the standby_exit action: arm the hook and honor explicit preferences."""

    request = payload.get("request")
    request = dict(request) if isinstance(request, Mapping) else {}
    preferences = payload.get("preferences")
    preferences = dict(preferences) if isinstance(preferences, Mapping) else {}
    match = payload.get("match")
    match = dict(match) if isinstance(match, Mapping) else {}

    outcome = request.get("requested_outcome") or request.get("intent")
    excluded = bool(request.get("excluded"))
    task_class = coarse_task_class(outcome or request.get("original"))

    armed = False
    hook_ref = None
    if isinstance(outcome, str) and outcome.strip() and not excluded:
        reason = str(match.get("classification") or "no_match")
        hook_ref = arm_hook(intent=outcome, task_class=task_class, reason=reason)
        armed = True

    ledger_ref = None
    statement = preferences.get("statement")
    stated_policy = preferences.get("policy")
    if isinstance(statement, str) and statement.strip() and stated_policy in POLICIES:
        stated_class = preferences.get("task_class")
        ledger_ref = append_ledger_entry(
            statement=statement,
            task_class=(
                stated_class
                if isinstance(stated_class, str) and stated_class
                else task_class
            ),
            policy=stated_policy,
        )

    presentation = None
    if armed:
        presentation = (
            "No saved Play covers this yet — continuing with the task normally. "
            "The agent should now complete the request itself (for API or provider work, "
            "the rote skill owns adapter catalog search and exploration). If the finished "
            "work turns out repeatable, settle it with `$play settle <one-line summary>` "
            "to judge it for saving."
        )
    return {
        "schema": SCHEMA,
        "kind": "standby",
        "ok": True,
        "event": "standby_recorded",
        "standby": {
            "armed": armed,
            "task_class": task_class,
            "hook_ref": hook_ref,
        },
        "preferences": {"ledger_ref": ledger_ref},
        "presentation_markdown": presentation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-standby")
    parser.add_argument("command", choices=["record"])
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    payload: dict[str, Any] = {}
    if arguments.stdin:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError as error:
            print(json_text({"ok": False, "error": str(error)}))
            return 1
    if not isinstance(payload, dict):
        print(json_text({"ok": False, "error": "stdin payload must be an object"}))
        return 1
    result = record_standby(payload)
    print(json_text(result))
    return 0
