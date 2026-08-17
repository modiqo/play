"""Owner-private sidekick state: the save-hook standby store and preference ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
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
CAPTURE_REF = re.compile(r"^cap_[A-Za-z0-9_-]{16,64}$")
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


def _scope_key(scope: str, value: str | None) -> str | None:
    if scope == "global":
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{scope} preferences require a scope_key")
    if scope == "project":
        return str(Path(value).expanduser().resolve())
    return value.strip()


def append_ledger_entry(
    *,
    statement: str,
    task_class: str,
    policy: str,
    scope: str = "global",
    scope_key: str | None = None,
    path: Path | None = None,
) -> str:
    """Append one scoped preference entry and return its content reference."""

    if policy not in POLICIES:
        raise ValueError(f"unknown preference policy {policy!r}")
    if scope not in SCOPES:
        raise ValueError(f"unknown preference scope {scope!r}")
    normalized_scope_key = _scope_key(scope, scope_key)
    target = path or _default_ledger_path()
    entries = load_ledger(target)
    entry = {
        "scope": scope,
        "task_class": task_class,
        "policy": policy,
        "statement": statement[:MAX_INTENT_CHARS],
        "recorded_at": _utc_now(),
        **(
            {"scope_key": normalized_scope_key}
            if normalized_scope_key is not None
            else {}
        ),
    }
    entries = [
        existing
        for existing in entries
        if not (
            existing.get("scope") == scope
            and existing.get("task_class") == task_class
            and existing.get("scope_key") == normalized_scope_key
        )
    ]
    entries.append(entry)
    atomic_write_json(target, {"schema": LEDGER_SCHEMA, "entries": entries})
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def preference_policy(
    task_class: str,
    *,
    session_id: str | None = None,
    project_path: str | None = None,
    path: Path | None = None,
) -> str | None:
    """Resolve the most specific applicable preference without widening its scope."""

    normalized_project = (
        _scope_key("project", project_path)
        if isinstance(project_path, str) and project_path.strip()
        else None
    )
    normalized_session = session_id.strip() if isinstance(session_id, str) else None
    selected: tuple[int, int, str] | None = None
    for index, entry in enumerate(load_ledger(path)):
        if entry.get("task_class") != task_class:
            continue
        scope = entry.get("scope")
        applies = scope == "global"
        rank = 0
        if scope == "project":
            applies = (
                normalized_project is not None
                and entry.get("scope_key") == normalized_project
            )
            rank = 1
        elif scope == "session":
            applies = (
                normalized_session is not None
                and entry.get("scope_key") == normalized_session
            )
            rank = 2
        if not applies:
            continue
        policy = entry.get("policy")
        if not isinstance(policy, str):
            continue
        candidate = (rank, index, policy)
        if selected is None or candidate[:2] >= selected[:2]:
            selected = candidate
    return selected[2] if selected is not None else None


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


def _load_captures(path: Path) -> list[dict[str, Any]]:
    store = _read_store(path)
    if not isinstance(store, Mapping) or store.get("schema") != STANDBY_SCHEMA:
        return []
    captures = store.get("captures")
    if not isinstance(captures, list):
        return []
    fresh: list[dict[str, Any]] = []
    now = time.time()
    for capture in captures:
        if not isinstance(capture, Mapping):
            continue
        created = capture.get("created_at_epoch")
        if isinstance(created, (int, float)) and now - created <= HOOK_TTL_SECONDS:
            fresh.append(dict(capture))
    return fresh


def _write_sidekick_store(
    path: Path, *, hooks: list[dict[str, Any]], captures: list[dict[str, Any]]
) -> None:
    atomic_write_json(
        path,
        {
            "schema": STANDBY_SCHEMA,
            "hooks": hooks[-MAX_HOOKS:],
            "captures": captures[-MAX_HOOKS:],
        },
    )


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
    _write_sidekick_store(target, hooks=hooks, captures=_load_captures(target))
    return hook_ref


def latest_hook(path: Path | None = None) -> dict[str, Any] | None:
    """Return the most recently armed unexpired save hook, if any."""

    hooks = _load_hooks(path or _default_standby_path())
    return hooks[-1] if hooks else None


def start_capture(
    *,
    intent: str,
    task_class: str,
    reason: str,
    path: Path | None = None,
    workspace_initializer: Any | None = None,
) -> dict[str, Any]:
    """Create an owner-private capture and its Rote workspace before work starts."""

    target = path or _default_standby_path()
    capture_ref = "cap_" + secrets.token_urlsafe(18)
    workspace = "play-capture-" + capture_ref.removeprefix("cap_").lower()
    initializer = workspace_initializer or _initialize_rote_workspace
    workspace_path = initializer(workspace)
    capture = {
        "reference": capture_ref,
        "intent": intent[:MAX_INTENT_CHARS],
        "task_class": task_class,
        "reason": reason[:MAX_INTENT_CHARS],
        "workspace": workspace,
        "workspace_path": str(workspace_path),
        "status": "active",
        "trajectory_ref": None,
        "created_at": _utc_now(),
        "created_at_epoch": time.time(),
    }
    captures = _load_captures(target)
    captures.append(capture)
    _write_sidekick_store(target, hooks=_load_hooks(target), captures=captures)
    return capture


def latest_capture(path: Path | None = None) -> dict[str, Any] | None:
    captures = _load_captures(path or _default_standby_path())
    active = [capture for capture in captures if capture.get("status") == "active"]
    return active[-1] if active else None


def capture_for_settle(
    reference: str,
    *,
    path: Path | None = None,
    trajectory_validator: Any | None = None,
) -> dict[str, Any]:
    """Resolve one explicit capture and prove its Rote trajectory already exists."""

    if not CAPTURE_REF.fullmatch(reference):
        raise ValueError("settle requires a valid capture handle")
    captures = _load_captures(path or _default_standby_path())
    capture_index = next(
        (index for index, item in enumerate(captures) if item.get("reference") == reference),
        None,
    )
    if capture_index is None:
        raise ValueError("capture handle is missing, expired, or already settled")
    capture = captures[capture_index]
    if capture.get("status") != "active":
        raise ValueError("capture handle is missing, expired, or already settled")
    validator = trajectory_validator or _validate_rote_trajectory
    trajectory_ref = validator(Path(str(capture.get("workspace_path"))))
    if not isinstance(trajectory_ref, str) or not trajectory_ref:
        raise ValueError("capture has no verified Rote trajectory")
    captures[capture_index] = {
        **capture,
        "status": "settling",
        "trajectory_ref": trajectory_ref,
        "settle_started_at": _utc_now(),
    }
    target = path or _default_standby_path()
    _write_sidekick_store(target, hooks=_load_hooks(target), captures=captures)
    return {**capture, "status": "verified", "trajectory_ref": trajectory_ref}


def _initialize_rote_workspace(workspace: str) -> Path:
    executable = shutil.which("rote")
    if executable is None:
        raise ValueError("capture requires rote on PATH")
    completed = subprocess.run(
        [executable, "init", workspace, "--seq", "--force"],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ValueError((completed.stderr or completed.stdout).strip() or "rote init failed")
    match = re.search(r"^Location:\s+(.+)$", completed.stdout, re.MULTILINE)
    if match is None:
        raise ValueError("rote init did not return a workspace location")
    workspace_path = Path(match.group(1).strip())
    if not workspace_path.is_dir():
        raise ValueError("rote capture workspace was not created")
    return workspace_path


def _validate_rote_trajectory(workspace_path: Path) -> str:
    executable = shutil.which("rote")
    if executable is None or not workspace_path.is_dir():
        raise ValueError("capture Rote workspace is unavailable")
    completed = subprocess.run(
        [executable, "ls"],
        cwd=workspace_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    evidence = "\n".join(
        part.rstrip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode != 0 or "No responses yet" in evidence:
        raise ValueError("capture has no verified Rote trajectory")
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    return "sha256:" + digest


def record_standby(
    payload: Mapping[str, Any], *, workspace_initializer: Any | None = None
) -> dict[str, Any]:
    """Handle the pre-work capture/normal decision and explicit preferences."""

    request = payload.get("request")
    request = dict(request) if isinstance(request, Mapping) else {}
    preferences = payload.get("preferences")
    preferences = dict(preferences) if isinstance(preferences, Mapping) else {}
    match = payload.get("match")
    match = dict(match) if isinstance(match, Mapping) else {}
    capture_input = payload.get("capture")
    capture_input = dict(capture_input) if isinstance(capture_input, Mapping) else {}

    outcome = request.get("requested_outcome") or request.get("intent")
    excluded = bool(request.get("excluded"))
    task_class = coarse_task_class(outcome or request.get("original"))

    decision = capture_input.get("decision")
    if decision not in {"capture", "normal"}:
        decision = "normal"
    capture: dict[str, Any] | None = None
    if decision == "capture" and isinstance(outcome, str) and outcome.strip() and not excluded:
        reason = str(match.get("classification") or "no_match")
        capture = start_capture(
            intent=outcome,
            task_class=(
                str(capture_input.get("task_class"))
                if capture_input.get("task_class")
                else task_class
            ),
            reason=str(capture_input.get("reason") or reason),
            workspace_initializer=workspace_initializer,
        )
        task_class = str(capture["task_class"])

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
    if capture is not None:
        presentation = (
            f"Capture `{capture['reference']}` started before execution. Complete the task "
            f"through Rote workspace `{capture['workspace']}`. Only this recorded trajectory "
            f"can later be settled with `$play settle {capture['reference']} <summary>`."
        )
    return {
        "schema": SCHEMA,
        "kind": "standby",
        "ok": True,
        "event": "standby_recorded",
        "standby": {
            "armed": capture is not None,
            "task_class": task_class,
            "hook_ref": capture.get("reference") if capture else None,
        },
        "capture": {
            "decision": "capture" if capture else "normal",
            "reason": (capture or capture_input).get("reason"),
            "task_class": task_class,
            "reference": capture.get("reference") if capture else None,
            "workspace": capture.get("workspace") if capture else None,
            "status": capture.get("status") if capture else "normal",
            "trajectory_ref": None,
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
