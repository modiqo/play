"""Asynchronous semantic projections over captured Rote workspaces.

Rote remains the raw evidence authority.  Play persists the complete semantic
graph and every opaque evidence reference; only the foreground viewport is
bounded.  Both are disposable and rebuildable from Rote plus typed Play events.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .journey_capabilities import (
    adapter_invocation,
    adapter_manifest_summary,
    attach_browser_lenses,
    capability_descriptor,
)
from .journey_world_model import capability_instances, enrich_operation
from .journey_effects import classify_effect
from .private_store import atomic_write_json, ensure_private_directory, load_json
from .state_home import state_path


SCHEMA = "play.journey-viewport/v1"
FULL_GRAPH_SCHEMA = "play.journey-graph/v1"
EVENT_SCHEMA = "play.journey-source-event/v1"
WORKER_SCHEMA = "play.journey-worker/v1"
PROJECTION_VERSION = "rules-v11"
DATABASE_SCHEMA_VERSION = 1

MAX_LABEL_CHARS = 120
MAX_INTENT_CHARS = 400
MAX_EVENT_BYTES = 4096
MAX_SNAPSHOT_BYTES = 512 * 1024
DEFAULT_IDLE_SECONDS = 600
ROTE_TIMEOUT_SECONDS = 8.0
RESPONSE_METADATA_LIMIT = 8 * 1024 * 1024
MAX_SNAPSHOT_NODES = 96
MAX_SNAPSHOT_EDGES = 384
MAX_SNAPSHOT_EVIDENCE_REFS = 128

NODE_KINDS = {
    "intent",
    "phase",
    "capability",
    "decision",
    "authority",
    "effect",
    "evidence",
    "artifact",
    "blocker",
    "recovery",
    "milestone",
    "learning",
    "play_candidate",
    "play",
}
NODE_STATUSES = {
    "planned",
    "active",
    "waiting",
    "blocked",
    "satisfied",
    "failed",
    "skipped",
    "superseded",
    "verified",
}
EDGE_KINDS = {
    "decomposes_into",
    "requires",
    "selects",
    "authorizes",
    "executes",
    "produces",
    "verifies",
    "blocked_by",
    "recovers",
    "derived_from",
    "refines",
    "crystallizes_into",
}

_SAFE_TEXT = re.compile(r"[^A-Za-z0-9 _.:/@+()#-]+")
_READ_ONLY_PROGRAMS = {
    "cat",
    "find",
    "grep",
    "head",
    "jq",
    "ls",
    "pwd",
    "rg",
    "sed",
    "stat",
    "tail",
    "wc",
    "which",
}
_SHELL_PROGRAMS = {"bash", "dash", "fish", "sh", "zsh"}
_INTERPRETER_PROGRAMS = {"deno", "node", "perl", "python", "python3", "ruby"}
_PROCESS_WRITE_PROGRAMS = {"cp", "install", "mkdir", "mv", "rm", "rmdir", "tee", "touch"}


class JourneyError(RuntimeError):
    """The semantic projection could not be built or read safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_label(value: object, *, fallback: str = "Work toward the outcome") -> str:
    text = " ".join(str(value or "").split())[:MAX_LABEL_CHARS]
    text = _SAFE_TEXT.sub("?", text).strip(" .")
    return text or fallback


def _journey_key(capture_ref: str) -> str:
    digest = hashlib.sha256(capture_ref.encode()).hexdigest()
    return f"journey-{digest[:24]}"


def journey_root(root: Path | None = None) -> Path:
    override = os.environ.get("PLAY_JOURNEY_ROOT")
    return root or (Path(override) if override else state_path("journeys"))


def journey_directory(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_root(root) / _journey_key(capture_ref)


def _snapshot_path(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "snapshot.json"


def _database_path(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "journey.sqlite3"


def _events_path(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "events.jsonl"


def _worker_path(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "worker.json"


def _claims_directory(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "claims"


def _standby_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    override = os.environ.get("PLAY_SIDEKICK_STANDBY_PATH")
    return Path(override) if override else state_path("standby.json")


def _capture(capture_ref: str, *, standby_path: Path | None = None) -> dict[str, Any] | None:
    try:
        store = load_json(_standby_path(standby_path))
    except (OSError, ValueError):
        return None
    captures = store.get("captures") if isinstance(store, Mapping) else None
    if not isinstance(captures, list):
        return None
    for item in captures:
        if isinstance(item, Mapping) and item.get("reference") == capture_ref:
            return dict(item)
    return None


def _jsonish(value: object, fallback: object) -> Any:
    if isinstance(value, (Mapping, list)):
        return value
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _parse_json_output(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            return value
    raise JourneyError("Rote returned malformed JSON")


def _event_id(parts: Sequence[object]) -> str:
    canonical = json.dumps(list(parts), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def append_source_event(
    capture_ref: str,
    *,
    kind: str,
    label: str,
    source: str,
    source_id: str,
    attributes: Mapping[str, object] | None = None,
    root: Path | None = None,
) -> bool:
    """Append one bounded source event without waiting for the projector."""

    if not capture_ref or not kind or not source_id:
        return False
    directory = journey_directory(capture_ref, root=root)
    try:
        ensure_private_directory(directory)
        event = {
            "schema": EVENT_SCHEMA,
            "id": _event_id((capture_ref, source, source_id, kind)),
            "kind": _safe_label(kind, fallback="milestone").lower().replace(" ", "_"),
            "label": _safe_label(label),
            "source": _safe_label(source, fallback="play"),
            "source_id": _safe_label(source_id),
            "recorded_at": _utc_now(),
            "attributes": {
                _safe_label(key, fallback="attribute")[:48]: _safe_label(value)
                for key, value in (attributes or {}).items()
                if value is not None
            },
        }
        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        encoded = line.encode()
        if len(encoded) > MAX_EVENT_BYTES:
            return False
        descriptor = os.open(
            _events_path(capture_ref, root=root),
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
        return True
    except OSError:
        return False


def record_capture_started(capture: Mapping[str, Any], *, root: Path | None = None) -> bool:
    reference = capture.get("reference")
    if not isinstance(reference, str):
        return False
    return append_source_event(
        reference,
        kind="capture_started",
        label=str(capture.get("intent") or "Captured exploration"),
        source="play",
        source_id=f"capture:{reference}",
        attributes={"task_class": capture.get("task_class")},
        root=root,
    )


_TRANSITION_EVENTS: dict[str, tuple[str, str]] = {
    "exploration_started": ("milestone", "Exploration started"),
    "exploration_prerequisite_ready": ("authority", "Connection prerequisite ready"),
    "exploration_prerequisite_presented": ("milestone", "Connection ready"),
    "exploration_goal_supplied": ("decision", "Useful exploration outcome selected"),
    "exploration_route_exhausted": ("blocker", "The selected route could not continue"),
    "exploration_retry_selected": ("recovery", "Another exploration route selected"),
    "exploration_stopped": ("milestone", "Exploration stopped"),
    "exploration_refinement_requested": ("decision", "Exploration outcome refined"),
    "outcome_verified": ("evidence", "Requested outcome verified"),
    "exploration_completion_presented": ("milestone", "Exploration outcome presented"),
    "worth_saving": ("play_candidate", "Reusable procedure identified"),
    "not_worth_saving": ("milestone", "Exploration completed as one-off work"),
    "candidate_ready": ("play_candidate", "Play candidate prepared"),
    "birth_captured": ("play", "Released Play provenance captured"),
    "birth_bound": ("play", "Published Play verified"),
}


def observe_transition(
    *, source: str, event: str, target: str, context: Mapping[str, Any], root: Path | None = None
) -> None:
    """Observe semantic Play transitions without changing controller behavior."""

    capture = context.get("capture")
    if not isinstance(capture, Mapping):
        return
    reference = capture.get("reference")
    if not isinstance(reference, str) or not reference:
        return
    semantic = _TRANSITION_EVENTS.get(event)
    if semantic is None:
        return
    kind, fallback_label = semantic
    transition_sequence = context.get("transition_seq")
    run_id = context.get("run_id")
    source_id = f"{run_id or 'run'}:{transition_sequence or 0}:{source}:{event}:{target}"
    goal = None
    exploration = context.get("exploration")
    if isinstance(exploration, Mapping):
        goal = exploration.get("goal")
    append_source_event(
        reference,
        kind=kind,
        label=_safe_label(goal, fallback=fallback_label) if kind == "decision" else fallback_label,
        source="play_transition",
        source_id=source_id,
        attributes={"event": event, "state": target},
        root=root,
    )


def _read_events(capture_ref: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    path = _events_path(capture_ref, root=root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, Mapping)
            and value.get("schema") == EVENT_SCHEMA
            and isinstance(value.get("id"), str)
        ):
            events[value["id"]] = dict(value)
    return list(events.values())


def _response_metadata(workspace: Path, response_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    """Read bounded envelope metadata and allowlisted typed policy receipts."""

    metadata: dict[int, dict[str, Any]] = {}
    for response_id in sorted(set(response_ids)):
        path = workspace / ".rote" / "responses" / f"@{response_id}.json"
        try:
            if path.stat().st_size > RESPONSE_METADATA_LIMIT:
                continue
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, Mapping):
            continue
        response = envelope.get("response")
        response = response if isinstance(response, Mapping) else {}
        request = envelope.get("request")
        request = request if isinstance(request, Mapping) else {}
        body = response.get("body")
        body = body if isinstance(body, Mapping) else {}
        status = response.get("status")
        ok = not isinstance(status, int) or status < 400
        duration = response.get("duration_ms")
        process_status = body.get("status")
        process_status = process_status if isinstance(process_status, Mapping) else {}
        exit_value = process_status.get("exit")
        exit_value = exit_value if isinstance(exit_value, Mapping) else {}
        exit_code = exit_value.get("code")
        if isinstance(exit_code, int):
            ok = exit_code == 0
        if process_status.get("timed_out") is True:
            ok = False
        if isinstance(process_status.get("duration_ms"), int):
            duration = process_status["duration_ms"]
        if isinstance(body.get("error"), Mapping) or isinstance(response.get("error"), Mapping):
            ok = False
        tokens = envelope.get("tokens")
        tokens = tokens if isinstance(tokens, Mapping) else {}
        request_tokens = tokens.get("request_tokens")
        response_tokens = tokens.get("response_tokens")
        total_tokens = tokens.get("total_tokens")
        item: dict[str, Any] = {
            "ok": bool(ok),
            "duration_ms": int(duration) if isinstance(duration, int) else 0,
            "tokens": int(total_tokens) if isinstance(total_tokens, int) else 0,
            # Rote names these from the capability transport's perspective.
            # Journey embodies the agent, so a capability response enters the
            # agent while its request leaves the agent.
            "input_tokens": int(response_tokens) if isinstance(response_tokens, int) else 0,
            "output_tokens": int(request_tokens) if isinstance(request_tokens, int) else 0,
        }
        endpoint = request.get("url")
        method = request.get("method")
        if isinstance(endpoint, str) and isinstance(method, str):
            item["request"] = {
                "endpoint": _safe_label(endpoint, fallback="external"),
                "method": _safe_label(method, fallback="request"),
            }
        policy = body.get("policy")
        policy = policy if isinstance(policy, Mapping) else {}
        risk_tags = policy.get("risk_tags")
        if isinstance(risk_tags, list):
            item["process_policy"] = {
                "state": _safe_label(policy.get("state"), fallback="unknown"),
                "decision": _safe_label(policy.get("decision"), fallback="unknown"),
                "risk_tags": sorted(
                    {
                        _safe_label(tag).lower()
                        for tag in risk_tags
                        if isinstance(tag, str)
                    }
                ),
            }
        metadata[response_id] = item
    return metadata


def _browser_response_metadata(workspace: Path) -> dict[int, dict[str, str]]:
    """Index Rote's typed browser ledger without copying page content."""

    path = workspace / ".rote" / "browser" / "ledger.json"
    try:
        if path.stat().st_size > RESPONSE_METADATA_LIMIT:
            return {}
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(ledger, Mapping):
        return {}
    indexed: dict[int, dict[str, str]] = {}
    collections = (
        ("assertions", "assertion", 0),
        ("snapshots", "snapshot", 1),
        ("waits", "wait", 2),
        ("actions", "action", 3),
        ("auth_restores", "authority", 4),
        ("policy_gates", "authority", 4),
        ("capture_failures", "blocker", 5),
    )
    priorities: dict[int, int] = {}
    for collection, kind, priority in collections:
        records = ledger.get(collection)
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            response_id = record.get("response_id")
            if not isinstance(response_id, int) or response_id < 1:
                continue
            current = indexed.setdefault(response_id, {})
            if priority >= priorities.get(response_id, -1):
                current["kind"] = kind
                priorities[response_id] = priority
            action_kind = record.get("action_kind")
            if isinstance(action_kind, str) and action_kind:
                current["action_kind"] = _safe_label(action_kind).lower()
    return indexed


def _workspace_response_ids(workspace: Path) -> list[int]:
    """Enumerate the complete typed response plane when the workspace changed."""

    responses = workspace / ".rote" / "responses"
    try:
        candidates = list(responses.glob("@*.json"))
    except OSError:
        return []
    response_ids: list[int] = []
    for path in candidates:
        value = path.stem.removeprefix("@")
        if value.isdigit() and int(value) > 0:
            response_ids.append(int(value))
    return sorted(set(response_ids))


def _nested_response_entries(
    metadata: Mapping[int, Mapping[str, Any]],
    attached_response_ids: set[int],
    *,
    first_sequence: int,
) -> list[dict[str, Any]]:
    """Project adapter responses emitted inside a Play executor as typed calls.

    Rote's command log intentionally records the outer Play process once. The
    response plane still contains each adapter request. Reconstructing the
    canonical adapter envelope from its typed endpoint and method preserves
    those operations without copying parameters, response bodies, or secrets.
    """

    entries: list[dict[str, Any]] = []
    sequence = first_sequence
    for response_id in sorted(metadata):
        if response_id in attached_response_ids:
            continue
        request = metadata[response_id].get("request")
        request = request if isinstance(request, Mapping) else {}
        endpoint = request.get("endpoint")
        operation = request.get("method")
        if (
            not isinstance(endpoint, str)
            or not endpoint.startswith("adapter/")
            or not isinstance(operation, str)
            or not operation
        ):
            continue
        adapter_id = endpoint.removeprefix("adapter/")
        if not adapter_id or "/" in adapter_id:
            continue
        wrapper = f"{adapter_id.replace('-', '_')}_call"
        entries.append(
            {
                "sequence": sequence,
                "command_type": "HttpRequest",
                "params": json.dumps(
                    {
                        "command": "HttpRequest",
                        "params": {
                            "endpoint": endpoint,
                            "body": {
                                "method": "tools/call",
                                "params": {
                                    "name": wrapper,
                                    "arguments": {
                                        "tool_name": operation,
                                        "arguments": {},
                                    },
                                },
                            },
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "response_ids": json.dumps([response_id]),
                "timestamp": None,
                "skip_export": False,
                "nested_response": True,
            }
        )
        sequence += 1
    return entries


def _command_payload(entry: Mapping[str, Any]) -> dict[str, Any]:
    outer = _jsonish(entry.get("params"), {})
    if not isinstance(outer, Mapping):
        return {}
    params = outer.get("params")
    return dict(params) if isinstance(params, Mapping) else dict(outer)


def _response_ids(entry: Mapping[str, Any]) -> list[int]:
    values = _jsonish(entry.get("response_ids"), [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, int) and value > 0]


def _process_operation(program: str, arguments: Sequence[Any]) -> str:
    """Return command structure without indexing user-controlled argument prose."""

    values = [str(value) for value in arguments if isinstance(value, str)]
    if program in _SHELL_PROGRAMS:
        shell_mode = next((value for value in values[:2] if value in {"-c", "-lc"}), None)
        return " ".join((program, shell_mode)) if shell_mode else program
    if program in _INTERPRETER_PROGRAMS:
        if not values:
            return program
        if values[0] in {"-c", "-e", "eval"}:
            return f"{program} {values[0]}"
        if values[0] == "-m":
            module = values[1] if len(values) > 1 else ""
            return " ".join(part for part in (program, "-m", module) if part)
        if values[0] in {"check", "fmt", "lint", "run", "task", "test"}:
            return f"{program} {values[0]}"
        candidate = Path(values[0]).name
        return f"{program} {candidate}" if len(candidate) <= 80 else program
    if program == "git":
        skip_next = False
        for value in values:
            if skip_next:
                skip_next = False
                continue
            if value in {"-C", "--git-dir", "--work-tree", "-c"}:
                skip_next = True
                continue
            if value.startswith("-"):
                continue
            return f"git {value}"
        return "git"
    if program in {"rote", "rtk"}:
        structural = [value for value in values if not value.startswith("-")][:4]
        return " ".join([program, *structural])
    if program in _READ_ONLY_PROGRAMS or program in _PROCESS_WRITE_PROGRAMS:
        return program
    verb = next((value for value in values if not value.startswith("-")), "")
    return " ".join(part for part in (program, verb) if part)


def _operation(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[str, str | None, str]:
    command_type = str(entry.get("command_type") or "Unknown")
    provider: str | None = None
    operation = command_type
    ephemeral = command_type
    if command_type == "HttpRequest":
        endpoint = str(payload.get("endpoint") or "external")
        adapter = adapter_invocation(payload)
        if adapter is not None:
            provider = str(adapter["adapter_id"])
        body = payload.get("body")
        body = body if isinstance(body, Mapping) else {}
        method = str(body.get("method") or payload.get("method") or "request")
        params = body.get("params")
        params = params if isinstance(params, Mapping) else {}
        name = params.get("name")
        operation = str(name) if isinstance(name, str) and name else method
        if adapter is not None:
            operations = adapter.get("operations")
            operations = operations if isinstance(operations, list) else []
            if adapter.get("phase") == "probe":
                operation = str(adapter.get("wrapper") or operation)
            elif len(operations) == 1:
                operation = str(operations[0])
            elif operations:
                operation = f"batch call ({len(operations)} operations)"
        ephemeral = " ".join((endpoint, method, operation))
    elif command_type.startswith("Process"):
        invocation = payload.get("invocation")
        invocation = invocation if isinstance(invocation, Mapping) else payload
        program = Path(str(invocation.get("program") or "process")).name
        arguments = invocation.get("args")
        arguments = arguments if isinstance(arguments, list) else []
        operation = _process_operation(program, arguments)
        # Retained only for non-process command families. Arbitrary shell arguments
        # may contain documentation or search text such as "sign-in" and must not
        # influence semantic classification.
        ephemeral = operation
    elif command_type == "DataQuery":
        provider = str(payload.get("adapter_id") or "data")
        operation = str(payload.get("tool_name") or "data query")
        ephemeral = f"{provider} {operation}"
    elif command_type == "For":
        adapter = adapter_invocation(payload)
        if adapter is not None:
            provider = str(adapter["adapter_id"])
            operations = adapter.get("operations")
            operations = operations if isinstance(operations, list) else []
            if len(operations) == 1:
                operation = str(operations[0])
            elif operations:
                operation = f"iterated batch ({len(operations)} operations)"
            else:
                operation = "iterate API request"
        else:
            method = _safe_label(payload.get("method"), fallback="request").upper()
            operation = f"iterate {method} request"
        ephemeral = operation
    elif command_type in {"QueryRead", "QueryExtract"}:
        operation = "query stored evidence"
        ephemeral = operation
    elif command_type == "Display":
        operation = "present stored evidence"
        ephemeral = operation
    elif command_type == "ComposeEmail":
        operation = "compose email artifact"
        ephemeral = operation
    elif command_type == "DepsCheck":
        operation = "check required capability"
        ephemeral = operation
    return _safe_label(operation, fallback=command_type), provider, ephemeral


def _classify(
    command_type: str,
    operation: str,
    capability: Mapping[str, Any],
    effect_profile: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Assign semantic role after typed Rote effect classification.

    Operation text remains display copy. It is never used to infer read/write
    posture. The only named operation below is Rote's exact auth contract.
    """

    posture = str(effect_profile.get("posture") or "unknown")
    risk_tags = {
        str(value)
        for value in effect_profile.get("risk_tags", [])
        if isinstance(value, str)
    }
    if command_type in {"QueryRead", "QueryExtract", "Display", "StreamFollow", "Inject"}:
        return "evidence", "supporting"
    if command_type == "ComposeEmail":
        return "artifact", None
    if command_type in {"InitSession", "DepsCheck"}:
        return "capability", None
    if command_type == "SetVariable":
        return "decision", "local"
    if command_type in {"HttpRequest", "DataQuery", "For"}:
        family = str(capability.get("family") or "")
        phase = str(capability.get("phase") or "")
        primitive = str(capability.get("primitive") or "")
        if phase in {"probe", "protocol"} or (
            primitive == "lease" and operation == "initialize"
        ):
            return "capability", None
        if operation == "adapter.auth.ensure":
            return "authority", None
        record_kind = str(capability.get("record_kind") or "")
        if family == "browser" and record_kind == "blocker":
            return "blocker", "failed"
        if family == "browser" and record_kind == "authority":
            return "authority", None
        if family == "browser" and primitive in {
            "inventory",
            "ledger",
            "slice",
            "lens",
            "wait",
        }:
            return "evidence", "supporting"
        if family in {"adapter", "browser"} or command_type in {"DataQuery", "For"}:
            return "effect", posture
        return "effect", "unknown"
    if command_type in {"ProcessBackgroundStatus", "ProcessBackgroundWait"}:
        return "phase", "supporting"
    if command_type == "ProcessBackgroundStart":
        return "effect", posture
    if command_type == "ProcessBackgroundStop":
        return "effect", posture
    if command_type.startswith("Process"):
        if "interactive_auth" in risk_tags:
            return "authority", None
        if posture == "read":
            return "phase", "inspection"
        if posture in {"write", "mixed"}:
            return "effect", posture
        return "phase", "unknown"
    return "phase", "supporting"


def normalize_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    response_metadata: Mapping[int, Mapping[str, Any]] | None = None,
    manifest_resolver: Callable[[str], Mapping[str, Any] | None] | None = None,
    tool_resolver: Callable[[str, str], Mapping[str, Any] | None] | None = None,
    browser_metadata: Mapping[int, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Normalize Rote command rows without retaining request or response payloads."""

    metadata = response_metadata or {}
    browser_records = browser_metadata or {}
    activities: list[dict[str, Any]] = []
    for raw in entries:
        sequence = raw.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            continue
        command_type = _safe_label(raw.get("command_type"), fallback="Unknown")
        payload = _command_payload(raw)
        response_ids = _response_ids(raw)
        operation, provider, _ephemeral = _operation(raw, payload)
        browser_record = next(
            (browser_records[item] for item in response_ids if item in browser_records),
            None,
        )
        capability = capability_descriptor(
            command_type,
            payload,
            operation,
            provider,
            manifest_resolver=manifest_resolver,
            browser_record=browser_record,
        )
        response_meta = [metadata[item] for item in response_ids if item in metadata]
        effect_profile = classify_effect(
            command_type,
            payload,
            capability,
            tool_resolver=tool_resolver,
            typed_receipts=response_meta,
        )
        kind, role = _classify(command_type, operation, capability, effect_profile)
        ok = all(bool(item.get("ok", True)) for item in response_meta)
        if not response_meta:
            ok = not bool(raw.get("skip_export"))
        duration_ms = sum(int(item.get("duration_ms") or 0) for item in response_meta)
        tokens = sum(int(item.get("tokens") or 0) for item in response_meta)
        input_tokens = sum(int(item.get("input_tokens") or 0) for item in response_meta)
        output_tokens = sum(int(item.get("output_tokens") or 0) for item in response_meta)
        source_tokens = payload.get("source_response_tokens")
        result_tokens = payload.get("result_tokens")
        source_response = payload.get("source_response")
        tokens_saved = (
            max(0, source_tokens - result_tokens)
            if isinstance(source_tokens, int) and isinstance(result_tokens, int)
            else 0
        )
        signature = f"{command_type}:{provider or '-'}:{operation.lower()}"
        activity = {
                "sequence": sequence,
                "command_type": command_type,
                "response_refs": [f"@{item}" for item in response_ids],
                "source_response": (
                    source_response
                    if isinstance(source_response, int) and source_response > 0
                    else None
                ),
                "operation": operation,
                "provider": _safe_label(provider) if provider else None,
                "capability": capability,
                "effect_profile": effect_profile,
                "kind": "blocker" if not ok else kind,
                "role": "failed" if not ok else role,
                "effect": role if kind == "effect" else None,
                "status": "failed" if not ok else "succeeded",
                "duration_ms": duration_ms,
                "tokens": tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tokens_saved": tokens_saved,
                "signature": hashlib.sha256(signature.encode()).hexdigest()[:24],
                "timestamp": raw.get("timestamp") if isinstance(raw.get("timestamp"), str) else None,
                "source": (
                    "typed_response"
                    if raw.get("nested_response") is True
                    else "command_log"
                ),
            }
        activities.append(activity)
    activities.sort(key=lambda item: item["sequence"])
    attach_browser_lenses(activities)
    for activity in activities:
        enrich_operation(activity)
    return activities


def normalize_dependencies(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    edges: set[tuple[int, int, str]] = set()
    for value in values:
        source = value.get("source_response")
        target = value.get("command_sequence")
        if not isinstance(source, int) or not isinstance(target, int):
            continue
        kind = _safe_label(value.get("dependency_type"), fallback="dependency")
        edges.add((source, target, kind))
    return [
        {"source_response": source, "target_sequence": target, "kind": kind}
        for source, target, kind in sorted(edges)
    ]


def _activity_label(activity: Mapping[str, Any]) -> str:
    kind = activity.get("kind")
    provider = activity.get("provider")
    provider_label = str(provider).replace("-", " ").title() if provider else None
    operation = _safe_label(activity.get("operation"))
    effect = activity.get("effect")
    if kind == "capability":
        return f"Find and validate {provider_label or operation} capability"
    if kind == "authority":
        return f"Connect {provider_label or operation}"
    if kind == "blocker":
        return f"Blocked while running {provider_label or operation}"
    if kind == "artifact":
        return f"Produce {operation}"
    if kind == "decision":
        return operation if operation and operation != "SetVariable" else "Record an exploration decision"
    if kind == "evidence" and activity.get("role") == "verification":
        return "Verify the result"
    if kind == "phase" and activity.get("role") == "inspection":
        return "Inspect relevant source and context"
    if kind == "effect" and effect == "read":
        return f"Retrieve data from {provider_label or operation}"
    if kind == "effect" and effect in {"write", "mixed"}:
        return f"Apply changes through {provider_label or operation}"
    if kind == "effect":
        return f"Use {provider_label or operation}"
    return operation


def _node_id(kind: str, label: str, first_sequence: int | str) -> str:
    digest = hashlib.sha256(f"{kind}|{label}|{first_sequence}".encode()).hexdigest()
    return "node_" + digest[:16]


def _empty_evidence() -> dict[str, list[Any]]:
    return {
        "play_events": [],
        "rote_commands": [],
        "rote_responses": [],
        "receipt_refs": [],
        "artifact_refs": [],
    }


def _append_activity(node: dict[str, Any], activity: Mapping[str, Any]) -> None:
    evidence = node["evidence"]
    sequence = int(activity["sequence"])
    if sequence not in evidence["rote_commands"]:
        evidence["rote_commands"].append(sequence)
    for reference in activity.get("response_refs", []):
        if reference not in evidence["rote_responses"]:
            evidence["rote_responses"].append(reference)
    telemetry = node["telemetry"]
    telemetry["duration_ms"] += int(activity.get("duration_ms") or 0)
    telemetry["payload_tokens"] += int(activity.get("tokens") or 0)
    telemetry["tokens_saved"] += int(activity.get("tokens_saved") or 0)
    node["activity_count"] += 1
    capability_ref = activity.get("capability_ref")
    if isinstance(capability_ref, str) and capability_ref not in node["capability_refs"]:
        node["capability_refs"].append(capability_ref)
    modality = activity.get("modality")
    if isinstance(modality, str) and modality not in node["modalities"]:
        node["modalities"].append(modality)
    lifecycle = activity.get("lifecycle_phase")
    if isinstance(lifecycle, str) and lifecycle not in node["lifecycle_phases"]:
        node["lifecycle_phases"].append(lifecycle)


def _new_node(activity: Mapping[str, Any], label: str, *, kind: str | None = None) -> dict[str, Any]:
    node_kind = kind or str(activity.get("kind") or "phase")
    status = "failed" if node_kind == "blocker" else "satisfied"
    if node_kind == "evidence" and activity.get("role") == "verification":
        status = "verified"
    node = {
        "id": _node_id(node_kind, label, int(activity["sequence"])),
        "kind": node_kind,
        "label": _safe_label(label),
        "status": status,
        "confidence": "deterministic",
        "effect": activity.get("effect"),
        "provider": activity.get("provider"),
        "activity_count": 0,
        "capability_refs": [],
        "modalities": [],
        "lifecycle_phases": [],
        "evidence": _empty_evidence(),
        "telemetry": {"duration_ms": 0, "payload_tokens": 0, "tokens_saved": 0},
        "first_sequence": int(activity["sequence"]),
        "last_sequence": int(activity["sequence"]),
    }
    _append_activity(node, activity)
    return node


def _capability_node(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Create an honest station when first use precedes explicit initialization."""

    initialization = instance.get("initialization")
    initialization = initialization if isinstance(initialization, Mapping) else {}
    sequence = initialization.get("first_sequence")
    sequence = sequence if isinstance(sequence, int) and sequence > 0 else None
    reference = str(instance.get("id") or "")
    label = _safe_label(instance.get("label"), fallback="Equipped capability")
    modality = str(instance.get("modality") or "")
    evidence = _empty_evidence()
    if sequence is not None:
        evidence["rote_commands"].append(sequence)
    return {
        "id": _node_id("capability", label, sequence or reference),
        "kind": "capability",
        "label": f"Equip {label} capability",
        "status": "failed" if instance.get("state") == "failed" else "satisfied",
        "confidence": "deterministic",
        "effect": None,
        "provider": str(instance.get("subject") or label),
        "activity_count": 0,
        "capability_refs": [reference] if reference else [],
        "modalities": [modality] if modality else [],
        "lifecycle_phases": ["initialize"],
        "evidence": evidence,
        "telemetry": {"duration_ms": 0, "payload_tokens": 0, "tokens_saved": 0},
        "first_sequence": sequence,
        "last_sequence": sequence,
    }


def _event_node(event: Mapping[str, Any], ordinal: int) -> dict[str, Any] | None:
    kind = str(event.get("kind") or "milestone")
    if kind == "capture_started":
        return None
    if kind not in NODE_KINDS:
        kind = "milestone"
    status = "failed" if kind == "blocker" else "satisfied"
    if kind in {"evidence", "play"}:
        status = "verified"
    label = _safe_label(event.get("label"))
    evidence = _empty_evidence()
    if isinstance(event.get("id"), str):
        evidence["play_events"].append(event["id"])
    return {
        "id": _node_id(kind, label, f"event-{ordinal}"),
        "kind": kind,
        "label": label,
        "status": status,
        "confidence": "typed_event",
        "effect": None,
        "provider": None,
        "activity_count": 1,
        "capability_refs": [],
        "modalities": [],
        "lifecycle_phases": [],
        "evidence": evidence,
        "telemetry": {"duration_ms": 0, "payload_tokens": 0, "tokens_saved": 0},
        "first_sequence": None,
        "last_sequence": None,
    }


def _semantic_signature(node: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        node.get("kind"),
        node.get("label"),
        node.get("status"),
        node.get("effect"),
        node.get("activity_count"),
        tuple(node.get("capability_refs", [])),
        tuple(node.get("modalities", [])),
        tuple(node.get("lifecycle_phases", [])),
    )


def _compact_nodes(
    nodes: list[dict[str, Any]], edges: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Bound only the viewport; the complete graph remains in SQLite and Rote."""

    if len(nodes) <= MAX_SNAPSHOT_NODES:
        return nodes, edges
    retained = [nodes[0], *nodes[-(MAX_SNAPSHOT_NODES - 2) :]]
    omitted = nodes[1 : len(nodes) - (MAX_SNAPSHOT_NODES - 2)]

    def telemetry_total(field: str) -> int:
        return sum(
            int(node.get("telemetry", {}).get(field) or 0)
            for node in omitted
            if isinstance(node.get("telemetry"), Mapping)
        )

    summary = {
        "id": "node_compacted_history",
        "kind": "milestone",
        "label": "Earlier exploration activity",
        "status": "satisfied",
        "confidence": "deterministic",
        "effect": None,
        "provider": None,
        "activity_count": sum(int(node.get("activity_count") or 0) for node in omitted),
        "capability_refs": sorted(
            {
                str(reference)
                for node in omitted
                for reference in node.get("capability_refs", [])
                if isinstance(reference, str)
            }
        ),
        "modalities": sorted(
            {
                str(modality)
                for node in omitted
                for modality in node.get("modalities", [])
                if isinstance(modality, str)
            }
        ),
        "lifecycle_phases": sorted(
            {
                str(phase)
                for node in omitted
                for phase in node.get("lifecycle_phases", [])
                if isinstance(phase, str)
            }
        ),
        "evidence": _empty_evidence(),
        "telemetry": {
            "duration_ms": telemetry_total("duration_ms"),
            "payload_tokens": telemetry_total("payload_tokens"),
            "tokens_saved": telemetry_total("tokens_saved"),
        },
        "first_sequence": min(
            (
                int(node["first_sequence"])
                for node in omitted
                if node.get("first_sequence") is not None
            ),
            default=None,
        ),
        "last_sequence": max(
            (
                int(node["last_sequence"])
                for node in omitted
                if node.get("last_sequence") is not None
            ),
            default=None,
        ),
    }
    retained.insert(1, summary)
    retained_ids = {str(node["id"]) for node in retained}
    bounded_edges = [
        edge
        for edge in edges
        if edge.get("source") in retained_ids and edge.get("target") in retained_ids
    ]
    bounded_edges.insert(
        0,
        {
            "source": "node_intent",
            "target": "node_compacted_history",
            "kind": "decomposes_into",
        },
    )
    return retained, bounded_edges


def build_graph(
    capture: Mapping[str, Any],
    *,
    activities: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
    stats: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] = (),
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the complete semantic graph from safe metadata without pruning."""

    reference = str(capture.get("reference") or "")
    origin_value = capture.get("origin")
    origin = dict(origin_value) if isinstance(origin_value, Mapping) else {}
    recalled = origin.get("kind") == "recalled_play"
    intent = _safe_label(capture.get("intent"), fallback="Captured exploration")[:MAX_INTENT_CHARS]
    root_status = "verified" if capture.get("trajectory_ref") else "active"
    intent_node = {
        "id": "node_intent",
        "kind": "intent",
        "label": intent,
        "status": root_status,
        "confidence": "recalled_play" if recalled else "play_capture",
        "effect": None,
        "provider": None,
        "activity_count": 0,
        "capability_refs": [],
        "modalities": [],
        "lifecycle_phases": [],
        "evidence": _empty_evidence(),
        "telemetry": {"duration_ms": 0, "payload_tokens": 0, "tokens_saved": 0},
        "first_sequence": None,
        "last_sequence": None,
    }
    nodes: list[dict[str, Any]] = [intent_node]
    nodes_by_id: dict[str, dict[str, Any]] = {"node_intent": intent_node}
    capabilities = capability_instances(activities)
    explicit_capability_refs = {
        str(activity["capability_ref"])
        for activity in activities
        if activity.get("kind") == "capability"
        and isinstance(activity.get("capability_ref"), str)
    }
    for instance in capabilities:
        if instance["id"] in explicit_capability_refs:
            continue
        station = _capability_node(instance)
        nodes.append(station)
        nodes_by_id[station["id"]] = station
    activity_to_node: dict[int, str] = {}
    response_to_node: dict[int, str] = {}
    failure_by_signature: dict[str, str] = {}
    current: dict[str, Any] | None = None
    has_nested_provider_work = any(
        activity.get("source") == "typed_response" for activity in activities
    )

    for activity in activities:
        sequence = int(activity["sequence"])
        kind = str(activity.get("kind") or "phase")
        role = activity.get("role")
        signature = str(activity.get("signature") or "")
        assigned: dict[str, Any] | None = None
        if (
            recalled
            and has_nested_provider_work
            and activity.get("source") == "command_log"
            and str(activity.get("command_type") or "").startswith("Process")
        ):
            # A recalled Play often runs through one local executor while Rote's
            # typed response plane records the provider operations it performs.
            # Keep the executor on the starting gate for audit and telemetry;
            # do not misrepresent it as the user's semantic journey.
            _append_activity(intent_node, activity)
            assigned = intent_node
        elif kind == "blocker":
            current = _new_node(activity, _activity_label(activity))
            nodes.append(current)
            nodes_by_id[current["id"]] = current
            failure_by_signature[signature] = current["id"]
        elif signature in failure_by_signature:
            label = f"Recover {_activity_label(activity).lower()}"
            current = _new_node(activity, label, kind="recovery")
            current["recovered_node"] = failure_by_signature.pop(signature)
            nodes.append(current)
            nodes_by_id[current["id"]] = current
        elif kind == "evidence" and role == "supporting":
            source_response = activity.get("source_response")
            source_node_id = (
                response_to_node.get(source_response)
                if isinstance(source_response, int)
                else None
            )
            assigned = nodes_by_id.get(source_node_id) if source_node_id else current
            if assigned is None:
                current = _new_node(activity, _activity_label(activity))
                nodes.append(current)
                nodes_by_id[current["id"]] = current
                assigned = current
            else:
                _append_activity(assigned, activity)
                assigned["last_sequence"] = max(
                    int(assigned.get("last_sequence") or sequence), sequence
                )
        elif kind == "phase" and role == "supporting" and current is not None:
            _append_activity(current, activity)
            current["last_sequence"] = sequence
        else:
            label = _activity_label(activity)
            groupable = (
                current is not None
                and current.get("kind") == kind
                and current.get("label") == label
                and kind not in {"blocker", "recovery", "decision", "artifact"}
            )
            if groupable and current is not None:
                _append_activity(current, activity)
                current["last_sequence"] = sequence
            else:
                current = _new_node(activity, label)
                nodes.append(current)
                nodes_by_id[current["id"]] = current
        assigned = assigned or current
        if assigned is not None:
            activity_to_node[sequence] = assigned["id"]
            for reference_value in activity.get("response_refs", []):
                if isinstance(reference_value, str) and reference_value.startswith("@"):
                    try:
                        response_to_node[int(reference_value[1:])] = assigned["id"]
                    except ValueError:
                        pass

    commands_value = stats.get("commands")
    commands_value = int(commands_value) if isinstance(commands_value, int) else len(activities)

    event_nodes = {
        (str(node.get("kind")), str(node.get("label"))): node for node in nodes
    }
    for ordinal, event in enumerate(events, 1):
        event_node = _event_node(event, ordinal)
        if event_node is None:
            continue
        key = (str(event_node["kind"]), str(event_node["label"]))
        existing_event_node = event_nodes.get(key)
        if existing_event_node is not None:
            existing_refs = existing_event_node["evidence"]["play_events"]
            for event_ref in event_node["evidence"]["play_events"]:
                if event_ref not in existing_refs:
                    existing_refs.append(event_ref)
                    existing_event_node["activity_count"] += 1
            continue
        nodes.append(event_node)
        event_nodes[key] = event_node

    visible_work = [
        node
        for node in nodes[1:]
        if node["kind"] not in {"blocker", "recovery"}
        and node["status"] not in {"verified", "failed"}
        and node.get("confidence") != "typed_event"
    ]
    if visible_work and capture.get("status") == "active":
        visible_work[-1]["status"] = "active"

    edges: list[dict[str, str]] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, kind: str) -> None:
        if source == target or kind not in EDGE_KINDS:
            return
        key = (source, target, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    for node in nodes[1:]:
        add_edge("node_intent", node["id"], "decomposes_into")
        recovered = node.get("recovered_node")
        if isinstance(recovered, str):
            add_edge(recovered, node["id"], "recovers")
    sequenced_nodes = sorted(
        (node for node in nodes[1:] if isinstance(node.get("first_sequence"), int)),
        key=lambda node: int(node["first_sequence"]),
    )
    for source_node, target_node in zip(sequenced_nodes, sequenced_nodes[1:]):
        add_edge(source_node["id"], target_node["id"], "derived_from")
    for dependency in dependencies:
        source = dependency.get("source_response")
        target = dependency.get("target_sequence")
        if not isinstance(source, int) or not isinstance(target, int):
            continue
        source_node = response_to_node.get(source)
        target_node = activity_to_node.get(target)
        if source_node and target_node:
            add_edge(source_node, target_node, "derived_from")

    capability_nodes: dict[str, str] = {}
    for node in nodes:
        if node.get("kind") != "capability":
            continue
        for reference in node.get("capability_refs", []):
            if isinstance(reference, str):
                capability_nodes.setdefault(reference, str(node["id"]))
    for node in nodes:
        for reference in node.get("capability_refs", []):
            station_id = capability_nodes.get(str(reference))
            if station_id is None or station_id == node.get("id"):
                continue
            if node.get("kind") == "authority":
                add_edge(station_id, str(node["id"]), "requires")
            elif node.get("kind") == "effect":
                add_edge(station_id, str(node["id"]), "executes")

    # Add the causal vocabulary used by people and renderers.  These edges are
    # a deterministic projection over the ordered semantic nodes: each source
    # selects its nearest compatible successor, stopping when a newer source
    # of the same kind supersedes it.  The chronological and Rote dependency
    # edges above remain present for audit and exact reconstruction.
    traversal_rules: tuple[tuple[str, str, str], ...] = (
        ("decision", "capability", "selects"),
        ("authority", "effect", "authorizes"),
        ("capability", "effect", "executes"),
        ("effect", "evidence", "produces"),
        ("evidence", "milestone", "verifies"),
        ("evidence", "play_candidate", "crystallizes_into"),
        ("blocker", "recovery", "recovers"),
    )
    ordered_nodes = nodes[1:]
    for source_kind, target_kind, edge_kind in traversal_rules:
        for source_index, source_node in enumerate(ordered_nodes):
            if source_node.get("kind") != source_kind:
                continue
            source_provider = source_node.get("provider")
            for target_node in ordered_nodes[source_index + 1 :]:
                if target_node.get("kind") == source_kind:
                    break
                if target_node.get("kind") != target_kind:
                    continue
                target_provider = target_node.get("provider")
                if (
                    source_provider
                    and target_provider
                    and source_provider != target_provider
                ):
                    continue
                add_edge(source_node["id"], target_node["id"], edge_kind)
                break

    previous_nodes = {
        str(node.get("id")): _semantic_signature(node)
        for node in (previous.get("nodes", []) if isinstance(previous, Mapping) else [])
        if isinstance(node, Mapping)
    }
    changed_node_ids = [
        node["id"]
        for node in nodes
        if previous_nodes.get(node["id"]) != _semantic_signature(node)
    ]
    previous_edges = {
        (item.get("source"), item.get("target"), item.get("kind"))
        for item in (previous.get("edges", []) if isinstance(previous, Mapping) else [])
        if isinstance(item, Mapping)
    }
    edge_set = {(item["source"], item["target"], item["kind"]) for item in edges}
    previous_capabilities = (
        previous.get("capabilities", []) if isinstance(previous, Mapping) else []
    )
    material = bool(
        [node_id for node_id in changed_node_ids if node_id != "node_intent"]
        or edge_set != previous_edges
        or json.dumps(capabilities, sort_keys=True, separators=(",", ":"))
        != json.dumps(previous_capabilities, sort_keys=True, separators=(",", ":"))
    )
    previous_generation = int(previous.get("generation") or 0) if isinstance(previous, Mapping) else 0
    previous_material = (
        int(previous.get("material_generation") or 0) if isinstance(previous, Mapping) else 0
    )
    current_node = next(
        (node["id"] for node in reversed(nodes) if node.get("status") in {"active", "blocked"}),
        "node_intent",
    )
    commands = commands_value
    responses = stats.get("responses")
    responses = int(responses) if isinstance(responses, int) else sum(
        len(activity.get("response_refs", [])) for activity in activities
    )
    token_savings = stats.get("token_savings")
    token_savings = token_savings if isinstance(token_savings, Mapping) else {}
    graph = {
        "schema": FULL_GRAPH_SCHEMA,
        "generation": previous_generation + 1,
        "material_generation": previous_material + (1 if material else 0),
        "projection_version": PROJECTION_VERSION,
        "state": str(capture.get("status") or "active"),
        "intent": {
            "label": intent,
            "source": "recalled_play" if recalled else "play_capture",
        },
        "origin": origin,
        "route": {
            "mode": "known" if recalled else "exploration",
            "exploration_skipped": recalled,
            "label": (
                "Known route · workflow discovery skipped"
                if recalled
                else "Exploration · route formed during the work"
            ),
        },
        "benefit": {
            "workflow_discovery_avoided": recalled,
            "capability_discovery_avoided": recalled,
            "typed_provider_operations": sum(
                activity.get("source") == "typed_response" for activity in activities
            ),
        },
        "capabilities": capabilities,
        "nodes": nodes,
        "edges": edges,
        "current_node": current_node,
        "presentation": {
            "has_material_change": material,
            # This is canonical graph metadata, not foreground presentation.
            # Retain the complete change set here; materialize_snapshot applies
            # the bounded viewport limit later.
            "changed_node_ids": changed_node_ids,
        },
        "telemetry": {
            "commands": commands,
            "window_commands": len(activities),
            "responses": responses,
            "duration_ms": sum(int(item.get("duration_ms") or 0) for item in activities),
            "payload_tokens": sum(int(item.get("tokens") or 0) for item in activities),
            "tokens_saved": int(token_savings.get("tokens_saved") or 0),
        },
        "source_cursor": {
            "play_events": len(events),
            "rote_command_sequence": max(
                [0, *[int(item.get("sequence") or 0) for item in activities]]
            ),
            "rote_response_id": max(
                [
                    0,
                    *[
                        int(reference_value[1:])
                        for item in activities
                        for reference_value in item.get("response_refs", [])
                        if isinstance(reference_value, str)
                        and reference_value.startswith("@")
                        and reference_value[1:].isdigit()
                    ],
                ]
            ),
        },
        "updated_at": _utc_now(),
        "journey_key": _journey_key(reference),
    }
    return graph


def materialize_snapshot(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Create a bounded foreground viewport without changing the canonical graph."""

    graph_nodes = [dict(node) for node in graph.get("nodes", []) if isinstance(node, Mapping)]
    graph_edges = [dict(edge) for edge in graph.get("edges", []) if isinstance(edge, Mapping)]
    nodes, edges = _compact_nodes(graph_nodes, graph_edges)
    total_evidence_refs = sum(
        len(values)
        for node in graph_nodes
        for values in (
            node.get("evidence", {}).values()
            if isinstance(node.get("evidence"), Mapping)
            else []
        )
        if isinstance(values, list)
    )
    retained_evidence_refs = 0
    for node in nodes:
        evidence = node.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        bounded_evidence: dict[str, list[Any]] = {}
        for key in _empty_evidence():
            values = evidence.get(key)
            values = list(values) if isinstance(values, list) else []
            bounded_evidence[key] = values[-MAX_SNAPSHOT_EVIDENCE_REFS:]
            retained_evidence_refs += len(bounded_evidence[key])
        node["evidence"] = bounded_evidence
    omitted_evidence_refs = max(0, total_evidence_refs - retained_evidence_refs)
    retained_ids = {str(node.get("id")) for node in nodes}
    presentation_value = graph.get("presentation")
    presentation_value = (
        dict(presentation_value) if isinstance(presentation_value, Mapping) else {}
    )
    changed_ids = presentation_value.get("changed_node_ids")
    changed_ids = list(changed_ids) if isinstance(changed_ids, list) else []
    presentation = {
        "has_material_change": bool(presentation_value.get("has_material_change")),
        "changed_node_ids": [
            value for value in changed_ids if isinstance(value, str) and value in retained_ids
        ][:64],
        "complete": len(nodes) == len(graph_nodes) and omitted_evidence_refs == 0,
        "total_nodes": len(graph_nodes),
        "total_edges": len(graph_edges),
        "evidence_refs_omitted": omitted_evidence_refs,
    }
    capability_values = graph.get("capabilities")
    capability_values = capability_values if isinstance(capability_values, list) else []
    bounded_capabilities: list[dict[str, Any]] = []
    for value in capability_values[:MAX_SNAPSHOT_NODES]:
        if not isinstance(value, Mapping):
            continue
        capability = dict(value)
        for key in ("operation_sequences", "evidence_sequences"):
            sequences = capability.get(key)
            sequences = list(sequences) if isinstance(sequences, list) else []
            capability[key] = sequences[-MAX_SNAPSHOT_EVIDENCE_REFS:]
        bounded_capabilities.append(capability)
    snapshot = {
        **{
            key: value
            for key, value in graph.items()
            if key not in {"capabilities", "nodes", "edges", "presentation"}
        },
        "schema": SCHEMA,
        "capabilities": bounded_capabilities,
        "nodes": nodes,
        "edges": edges[:MAX_SNAPSHOT_EDGES],
        "presentation": presentation,
    }
    if len(snapshot["edges"]) != len(graph_edges):
        snapshot["presentation"]["complete"] = False
    if len(bounded_capabilities) != len(capability_values):
        snapshot["presentation"]["complete"] = False
    current_node = snapshot.get("current_node")
    if current_node not in retained_ids:
        snapshot["current_node"] = next(
            (
                node["id"]
                for node in reversed(nodes)
                if node.get("status") in {"active", "blocked"}
            ),
            "node_intent",
        )
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise JourneyError("Journey snapshot exceeds the bounded size limit")
    return snapshot


def build_snapshot(
    capture: Mapping[str, Any],
    *,
    activities: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
    stats: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] = (),
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility helper for building the bounded foreground viewport."""

    graph = build_graph(
        capture,
        activities=activities,
        dependencies=dependencies,
        stats=stats,
        events=events,
        previous=previous,
    )
    return materialize_snapshot(graph)


def load_snapshot(capture_ref: str, *, root: Path | None = None) -> dict[str, Any] | None:
    path = _snapshot_path(capture_ref, root=root)
    try:
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            return None
        value = load_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        return None
    nodes = value.get("nodes")
    edges = value.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None
    return dict(value)


def _run_rote_json(workspace: Path, arguments: Sequence[str]) -> Any:
    executable = shutil.which("rote")
    if executable is None:
        raise JourneyError("rote is not available")
    completed = subprocess.run(
        [executable, *arguments],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        timeout=ROTE_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise JourneyError(detail[:300] or f"rote {' '.join(arguments)} failed")
    return _parse_json_output(completed.stdout)


def _workspace_fingerprint(workspace: Path) -> str:
    parts: list[str] = []
    for relative in (
        Path(".rote/workspace.db"),
        Path(".rote/workspace.db-wal"),
        Path(".rote/workspace.marker"),
        Path(".rote/browser/ledger.json"),
    ):
        path = workspace / relative
        try:
            stat = path.stat()
        except OSError:
            continue
        # Opening SQLite for a read can create or retouch an empty WAL.  It is
        # observer noise, not workspace activity; including it makes the
        # detached projector continuously trigger itself.
        if relative.name == "workspace.db-wal" and stat.st_size == 0:
            continue
        parts.append(f"{relative}:{stat.st_size}:{stat.st_mtime_ns}")
    responses = workspace / ".rote" / "responses"
    try:
        stat = responses.stat()
        parts.append(f"responses:{stat.st_size}:{stat.st_mtime_ns}")
    except OSError:
        pass
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _event_fingerprint(capture_ref: str, *, root: Path | None = None) -> str:
    try:
        stat = _events_path(capture_ref, root=root).stat()
    except OSError:
        return ""
    return f"{stat.st_size}:{stat.st_mtime_ns}"


@contextmanager
def _graph_database(
    capture_ref: str, *, root: Path | None = None
) -> Iterator[sqlite3.Connection]:
    directory = journey_directory(capture_ref, root=root)
    ensure_private_directory(directory)
    path = _database_path(capture_ref, root=root)
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activities (
                sequence INTEGER PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dependencies (
                source_response INTEGER NOT NULL,
                target_sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                PRIMARY KEY (source_response, target_sequence, kind)
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                ordinal INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                kind TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY (source, target, kind)
            );
            CREATE INDEX IF NOT EXISTS activities_sequence_idx ON activities(sequence);
            CREATE INDEX IF NOT EXISTS dependencies_target_idx ON dependencies(target_sequence);
            CREATE INDEX IF NOT EXISTS nodes_ordinal_idx ON nodes(ordinal);
            CREATE INDEX IF NOT EXISTS edges_ordinal_idx ON edges(ordinal);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('database_schema_version', ?)",
            (json.dumps(DATABASE_SCHEMA_VERSION),),
        )
        yield connection
        connection.commit()
    except sqlite3.DatabaseError as error:
        connection.rollback()
        raise JourneyError(f"Journey database failure: {error}") from error
    finally:
        connection.close()
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            try:
                candidate.chmod(0o600)
            except OSError:
                pass


def _decode_meta(rows: Sequence[tuple[str, str]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, encoded in rows:
        try:
            values[key] = json.loads(encoded)
        except json.JSONDecodeError:
            continue
    return values


def _graph_from_database(connection: sqlite3.Connection, meta: Mapping[str, Any]) -> dict[str, Any] | None:
    header = meta.get("graph_header")
    if not isinstance(header, Mapping) or header.get("schema") != FULL_GRAPH_SCHEMA:
        return None
    nodes: list[dict[str, Any]] = []
    for (encoded,) in connection.execute("SELECT payload FROM nodes ORDER BY ordinal"):
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            nodes.append(dict(value))
    edges: list[dict[str, Any]] = []
    for source, target, kind in connection.execute(
        "SELECT source, target, kind FROM edges ORDER BY ordinal"
    ):
        edges.append({"source": source, "target": target, "kind": kind})
    return {**dict(header), "nodes": nodes, "edges": edges}


def load_graph(capture_ref: str, *, root: Path | None = None) -> dict[str, Any] | None:
    """Load the complete persisted semantic graph, never the Rote payload DAG."""

    if not _database_path(capture_ref, root=root).is_file():
        return None
    with _graph_database(capture_ref, root=root) as connection:
        meta = _decode_meta(list(connection.execute("SELECT key, value FROM meta")))
        return _graph_from_database(connection, meta)


def _load_source(capture_ref: str, *, root: Path | None = None) -> dict[str, Any]:
    if not _database_path(capture_ref, root=root).is_file():
        return {
            "fingerprint": None,
            "command_count": 0,
            "response_count": 0,
            "activities": [],
            "dependencies": [],
            "graph": None,
        }
    with _graph_database(capture_ref, root=root) as connection:
        meta = _decode_meta(list(connection.execute("SELECT key, value FROM meta")))
        activities: list[dict[str, Any]] = []
        for (encoded,) in connection.execute(
            "SELECT payload FROM activities ORDER BY sequence"
        ):
            try:
                value = json.loads(encoded)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                activities.append(dict(value))
        dependencies = [
            {"source_response": source, "target_sequence": target, "kind": kind}
            for source, target, kind in connection.execute(
                "SELECT source_response, target_sequence, kind "
                "FROM dependencies ORDER BY source_response, target_sequence, kind"
            )
        ]
        return {
            "fingerprint": meta.get("fingerprint"),
            "command_count": int(meta.get("command_count") or 0),
            "response_count": int(meta.get("response_count") or 0),
            "activities": activities,
            "dependencies": dependencies,
            "graph": _graph_from_database(connection, meta),
        }


def _persist_graph_state(
    capture_ref: str,
    *,
    fingerprint: str,
    command_count: int,
    response_count: int = 0,
    activities: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
    reset_sources: bool = False,
    replace_dependencies: bool = True,
    root: Path | None = None,
) -> None:
    """Atomically replace the complete semantic projection without pruning it."""

    with _graph_database(capture_ref, root=root) as connection:
        if reset_sources:
            connection.execute("DELETE FROM activities")
        connection.executemany(
            "INSERT OR REPLACE INTO activities(sequence, payload) VALUES(?, ?)",
            [
                (
                    int(activity["sequence"]),
                    json.dumps(dict(activity), sort_keys=True, separators=(",", ":")),
                )
                for activity in activities
            ],
        )
        if replace_dependencies:
            connection.execute("DELETE FROM dependencies")
            connection.executemany(
                "INSERT INTO dependencies(source_response, target_sequence, kind) VALUES(?, ?, ?)",
                [
                    (
                        int(dependency["source_response"]),
                        int(dependency["target_sequence"]),
                        str(dependency["kind"]),
                    )
                    for dependency in dependencies
                ],
            )

        existing_nodes = {
            node_id: (ordinal, payload)
            for node_id, ordinal, payload in connection.execute(
                "SELECT id, ordinal, payload FROM nodes"
            )
        }
        current_nodes = {
            str(node["id"]): (
                ordinal,
                json.dumps(dict(node), sort_keys=True, separators=(",", ":")),
            )
            for ordinal, node in enumerate(graph.get("nodes", []))
            if isinstance(node, Mapping)
        }
        stale_nodes = set(existing_nodes) - set(current_nodes)
        connection.executemany(
            "DELETE FROM nodes WHERE id = ?", [(node_id,) for node_id in stale_nodes]
        )
        connection.executemany(
            "INSERT OR REPLACE INTO nodes(id, ordinal, payload) VALUES(?, ?, ?)",
            [
                (node_id, ordinal, payload)
                for node_id, (ordinal, payload) in current_nodes.items()
                if existing_nodes.get(node_id) != (ordinal, payload)
            ],
        )

        existing_edges = {
            (source, target, kind): ordinal
            for source, target, kind, ordinal in connection.execute(
                "SELECT source, target, kind, ordinal FROM edges"
            )
        }
        current_edges = {
            (str(edge["source"]), str(edge["target"]), str(edge["kind"])): ordinal
            for ordinal, edge in enumerate(graph.get("edges", []))
            if isinstance(edge, Mapping)
        }
        stale_edges = set(existing_edges) - set(current_edges)
        connection.executemany(
            "DELETE FROM edges WHERE source = ? AND target = ? AND kind = ?",
            list(stale_edges),
        )
        connection.executemany(
            "INSERT OR REPLACE INTO edges(source, target, kind, ordinal) VALUES(?, ?, ?, ?)",
            [
                (*edge, ordinal)
                for edge, ordinal in current_edges.items()
                if existing_edges.get(edge) != ordinal
            ],
        )
        header = {
            key: value for key, value in graph.items() if key not in {"nodes", "edges"}
        }
        meta = {
            "fingerprint": fingerprint,
            "command_count": command_count,
            "response_count": response_count,
            "graph_header": header,
        }
        connection.executemany(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            [
                (key, json.dumps(value, sort_keys=True, separators=(",", ":")))
                for key, value in meta.items()
            ],
        )


def refresh_capture(
    capture: Mapping[str, Any], *, root: Path | None = None, force: bool = False
) -> dict[str, Any] | None:
    """Refresh one Journey from Rote, entirely outside the foreground hook."""

    reference = capture.get("reference")
    workspace_value = capture.get("workspace_path")
    if not isinstance(reference, str) or not isinstance(workspace_value, str):
        return None
    workspace = Path(workspace_value)
    if not workspace.is_dir() or not (workspace / ".rote").is_dir():
        return None
    fingerprint = _workspace_fingerprint(workspace)
    source = _load_source(reference, root=root)
    previous = load_snapshot(reference, root=root)
    previous_graph = source.get("graph")
    previous_graph = previous_graph if isinstance(previous_graph, Mapping) else previous
    projection_changed = not isinstance(previous_graph, Mapping) or (
        previous_graph.get("projection_version") != PROJECTION_VERSION
    )
    events = _read_events(reference, root=root)
    if not force and not projection_changed and fingerprint == source.get("fingerprint"):
        persisted_count = int(source.get("command_count") or 0)
        if (
            previous is not None
            and int(previous.get("source_cursor", {}).get("play_events") or 0) == len(events)
            and int(previous.get("source_cursor", {}).get("rote_command_sequence") or 0)
            >= persisted_count
        ):
            return previous
        if (
            isinstance(previous_graph, Mapping)
            and int(previous_graph.get("source_cursor", {}).get("play_events") or 0)
            == len(events)
            and int(previous_graph.get("source_cursor", {}).get("rote_command_sequence") or 0)
            >= persisted_count
        ):
            snapshot = materialize_snapshot(previous_graph)
            atomic_write_json(_snapshot_path(reference, root=root), snapshot)
            return snapshot

    stats_value = _run_rote_json(workspace, ["workspace", "stats", "--json"])
    if not isinstance(stats_value, Mapping):
        raise JourneyError("Rote workspace stats is not an object")
    command_count = stats_value.get("commands")
    command_count = int(command_count) if isinstance(command_count, int) else 0
    response_count = stats_value.get("responses")
    response_count = int(response_count) if isinstance(response_count, int) else 0
    prior_count = int(source.get("command_count") or 0)
    prior_response_count = int(source.get("response_count") or 0)
    activities = [dict(item) for item in source.get("activities", []) if isinstance(item, Mapping)]
    reset_sources = (
        force
        or projection_changed
        or command_count < prior_count
        or response_count < prior_response_count
    )
    if reset_sources:
        prior_count = 0
        activities = []
    delta = max(0, command_count - prior_count)
    new_activities: list[dict[str, Any]] = []
    raw_entries: list[dict[str, Any]] = []
    if delta:
        log_arguments = ["workspace", "inspect", "log", "--json"]
        if prior_count:
            log_arguments = ["workspace", "inspect", "log", "--last", str(delta), "--json"]
        log_value = _run_rote_json(workspace, log_arguments)
        if not isinstance(log_value, list):
            raise JourneyError("Rote workspace log is not an array")
        raw_entries = [dict(item) for item in log_value if isinstance(item, Mapping)]

    if delta or response_count != prior_response_count or reset_sources:
        workspace_response_ids = _workspace_response_ids(workspace)
        response_ids = [
            response_id for item in raw_entries for response_id in _response_ids(item)
        ]
        metadata = _response_metadata(
            workspace,
            [*workspace_response_ids, *response_ids],
        )
        browser_metadata = _browser_response_metadata(workspace)
        new_activities = normalize_entries(
            raw_entries,
            response_metadata=metadata,
            manifest_resolver=adapter_manifest_summary,
            browser_metadata=browser_metadata,
        )
        attached_response_ids = {
            int(reference[1:])
            for activity in [*activities, *new_activities]
            for reference in activity.get("response_refs", [])
            if isinstance(reference, str)
            and reference.startswith("@")
            and reference[1:].isdigit()
        }
        first_nested_sequence = max(
            [
                0,
                *[int(item.get("sequence") or 0) for item in activities],
                *[int(item.get("sequence") or 0) for item in new_activities],
            ]
        ) + 1
        nested_entries = _nested_response_entries(
            metadata,
            attached_response_ids,
            first_sequence=first_nested_sequence,
        )
        new_activities.extend(
            normalize_entries(
                nested_entries,
                response_metadata=metadata,
                manifest_resolver=adapter_manifest_summary,
                browser_metadata=browser_metadata,
            )
        )
        by_sequence = {int(item["sequence"]): item for item in activities}
        by_sequence.update({int(item["sequence"]): item for item in new_activities})
        activities = [by_sequence[key] for key in sorted(by_sequence)]
        attach_browser_lenses(activities)

    for activity in activities:
        enrich_operation(activity)

    dependencies = [
        dict(item) for item in source.get("dependencies", []) if isinstance(item, Mapping)
    ]
    deps_due = force or delta >= 5 or not dependencies or command_count == 0
    if deps_due:
        deps_value = _run_rote_json(workspace, ["workspace", "inspect", "deps", "--json"])
        if isinstance(deps_value, list):
            dependencies = normalize_dependencies(
                [dict(item) for item in deps_value if isinstance(item, Mapping)]
            )

    graph = build_graph(
        capture,
        activities=activities,
        dependencies=dependencies,
        stats=stats_value,
        events=events,
        previous=previous_graph,
    )
    _persist_graph_state(
        reference,
        fingerprint=fingerprint,
        command_count=command_count,
        response_count=response_count,
        activities=activities if reset_sources else new_activities,
        dependencies=dependencies,
        graph=graph,
        reset_sources=reset_sources,
        replace_dependencies=deps_due,
        root=root,
    )
    snapshot = materialize_snapshot(graph)
    atomic_write_json(_snapshot_path(reference, root=root), snapshot)
    return snapshot


@contextmanager
def _worker_lease(capture_ref: str, *, root: Path | None = None) -> Iterator[bool]:
    directory = journey_directory(capture_ref, root=root)
    ensure_private_directory(directory)
    path = directory / "lease"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            yield False
            return
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode())
        yield True
    finally:
        if acquired:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def _write_worker_health(
    capture_ref: str,
    *,
    state: str,
    started_at: str,
    generation: int = 0,
    detail: str | None = None,
    root: Path | None = None,
) -> None:
    payload = {
        "schema": WORKER_SCHEMA,
        "pid": os.getpid(),
        "state": state,
        "started_at": started_at,
        "heartbeat_at": _utc_now(),
        "generation": generation,
        **({"detail": _safe_label(detail)} if detail else {}),
    }
    try:
        atomic_write_json(_worker_path(capture_ref, root=root), payload)
    except ValueError:
        pass


def run_worker(
    capture_ref: str,
    *,
    standby_path: Path | None = None,
    root: Path | None = None,
    once: bool = False,
    idle_seconds: int = DEFAULT_IDLE_SECONDS,
) -> int:
    started_at = _utc_now()
    try:
        os.nice(10)
    except OSError:
        pass
    with _worker_lease(capture_ref, root=root) as acquired:
        if not acquired:
            return 0
        idle_started = time.monotonic()
        delay = 0.25
        last_fingerprint: str | None = None
        while True:
            capture = _capture(capture_ref, standby_path=standby_path)
            if capture is None:
                _write_worker_health(
                    capture_ref, state="stopped", started_at=started_at, detail="capture unavailable", root=root
                )
                return 0
            workspace_value = capture.get("workspace_path")
            workspace = Path(workspace_value) if isinstance(workspace_value, str) else None
            workspace_fingerprint = (
                _workspace_fingerprint(workspace) if workspace and workspace.is_dir() else ""
            )
            fingerprint = (
                f"{workspace_fingerprint}:{_event_fingerprint(capture_ref, root=root)}"
            )
            changed = fingerprint != last_fingerprint
            try:
                snapshot = refresh_capture(capture, root=root, force=once)
                generation = int(snapshot.get("generation") or 0) if snapshot else 0
                _write_worker_health(
                    capture_ref, state="running", started_at=started_at, generation=generation, root=root
                )
            except Exception as error:  # noqa: BLE001 - projection may never break exploration
                _write_worker_health(
                    capture_ref,
                    state="degraded",
                    started_at=started_at,
                    detail=str(error)[:MAX_LABEL_CHARS],
                    root=root,
                )
            last_fingerprint = fingerprint
            if once:
                return 0
            if capture.get("status") != "active":
                _write_worker_health(capture_ref, state="stopped", started_at=started_at, root=root)
                return 0
            if changed:
                idle_started = time.monotonic()
                delay = 0.5
            else:
                delay = min(15.0, max(1.0, delay * 2))
            if time.monotonic() - idle_started >= max(1, idle_seconds):
                _write_worker_health(capture_ref, state="idle_exit", started_at=started_at, root=root)
                return 0
            time.sleep(delay)


def schedule_worker(
    capture: Mapping[str, Any], *, standby_path: Path | None = None
) -> bool:
    """Detach a best-effort worker; startup never affects capture creation."""

    if os.environ.get("PLAY_JOURNEY_DISABLE") == "1":
        return False
    reference = capture.get("reference")
    if not isinstance(reference, str) or not reference:
        return False
    root = Path(__file__).resolve().parents[3]
    executable = root / "scripts" / "bin" / "play-journey"
    if not executable.is_file():
        return False
    command = [sys.executable, str(executable), "worker", "--capture", reference]
    environment = os.environ.copy()
    if standby_path is not None:
        environment["PLAY_SIDEKICK_STANDBY_PATH"] = str(standby_path)
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def _fast_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def claim_snapshot(
    capture: Mapping[str, Any],
    *,
    root: Path | None = None,
    force: bool = False,
    min_interval_seconds: int = 120,
) -> dict[str, Any] | None:
    """Claim one already-built semantic generation without invoking Rote."""

    reference = capture.get("reference")
    if not isinstance(reference, str):
        return None
    started = time.perf_counter_ns()
    snapshot = load_snapshot(reference, root=root)
    if snapshot is None:
        return None
    presentation = snapshot.get("presentation")
    if not isinstance(presentation, Mapping) or not presentation.get("has_material_change"):
        return None
    material_generation = snapshot.get("material_generation")
    if not isinstance(material_generation, int) or material_generation < 1:
        return None
    directory = journey_directory(reference, root=root)
    presented_path = directory / "presented.json"
    try:
        presented = load_json(presented_path)
    except (OSError, ValueError):
        presented = {}
    if isinstance(presented, Mapping):
        if int(presented.get("material_generation") or 0) >= material_generation:
            return None
        claimed_at = presented.get("claimed_at_epoch")
        if (
            not force
            and isinstance(claimed_at, (int, float))
            and time.time() - claimed_at < max(0, min_interval_seconds)
        ):
            return None
    if (time.perf_counter_ns() - started) / 1_000_000 > 25 and not force:
        return None
    claims = _claims_directory(reference, root=root)
    try:
        ensure_private_directory(claims)
        descriptor = os.open(
            claims / f"{material_generation}.claim",
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
    except FileExistsError:
        return None
    except OSError:
        return None
    try:
        _fast_atomic_json(
            presented_path,
            {
                "material_generation": material_generation,
                "claimed_at": _utc_now(),
                "claimed_at_epoch": time.time(),
            },
        )
    except OSError:
        pass
    return snapshot


def render_snapshot(snapshot: Mapping[str, Any]) -> str:
    """Render semantic progress; raw operation rows remain an explicit diagnostic."""

    intent = snapshot.get("intent")
    intent_label = intent.get("label") if isinstance(intent, Mapping) else "Captured exploration"
    nodes = [item for item in snapshot.get("nodes", []) if isinstance(item, Mapping)]
    work = [item for item in nodes if item.get("kind") != "intent"]
    markers = {
        "verified": "✓",
        "satisfied": "✓",
        "active": "●",
        "waiting": "○",
        "planned": "○",
        "blocked": "!",
        "failed": "✗",
        "recovery": "↻",
    }
    lines = ["📍 **Exploration progress**", "", f"**{_safe_label(intent_label)}**"]
    for node in work[-8:]:
        status = str(node.get("status") or "planned")
        marker = "↻" if node.get("kind") == "recovery" else markers.get(status, "·")
        suffix = ""
        count = node.get("activity_count")
        if isinstance(count, int) and count > 1:
            suffix = f" · {count} recorded operations"
        lines.append(f"- {marker} {_safe_label(node.get('label'))}{suffix}")
    telemetry = snapshot.get("telemetry")
    if isinstance(telemetry, Mapping):
        commands = int(telemetry.get("commands") or 0)
        window_commands = int(telemetry.get("window_commands") or commands)
        duration_label = "recent operation time" if window_commands < commands else "operation time"
        lines.extend(
            [
                "",
                (
                    f"Evidence: {commands} recorded steps · "
                    f"{int(telemetry.get('duration_ms') or 0)}ms {duration_label} · "
                    f"{int(telemetry.get('tokens_saved') or 0)} tokens avoided"
                ),
            ]
        )
    presentation = snapshot.get("presentation")
    if isinstance(presentation, Mapping) and presentation.get("complete") is False:
        lines.extend(
            [
                "",
                (
                    f"Viewport: {len(nodes)} of {int(presentation.get('total_nodes') or 0)} "
                    "semantic nodes shown; the complete Journey remains persisted."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "Exploration remains active. Keep steering, try another tool, or use "
            "`direct: <task>` for one turn and return with `continue exploration`.",
        ]
    )
    return "\n".join(lines)


def doctor(capture_ref: str, *, root: Path | None = None) -> dict[str, Any]:
    snapshot = load_snapshot(capture_ref, root=root)
    graph = load_graph(capture_ref, root=root)
    try:
        worker = load_json(_worker_path(capture_ref, root=root))
    except (OSError, ValueError):
        worker = None
    return {
        "schema": "play.journey-doctor/v1",
        "ok": snapshot is not None,
        "journey_key": _journey_key(capture_ref),
        "snapshot": {
            "present": snapshot is not None,
            "generation": snapshot.get("generation") if snapshot else None,
            "material_generation": snapshot.get("material_generation") if snapshot else None,
            "nodes": len(snapshot.get("nodes", [])) if snapshot else 0,
            "edges": len(snapshot.get("edges", [])) if snapshot else 0,
        },
        "graph": {
            "present": graph is not None,
            "generation": graph.get("generation") if graph else None,
            "nodes": len(graph.get("nodes", [])) if graph else 0,
            "edges": len(graph.get("edges", [])) if graph else 0,
            "complete": graph is not None,
        },
        "worker": worker if isinstance(worker, Mapping) else None,
    }


def active_capture_reference(*, standby_path: Path | None = None) -> str | None:
    """Resolve the newest active capture whose Rote workspace still exists."""

    try:
        store = load_json(_standby_path(standby_path))
    except (OSError, ValueError):
        return None
    captures = store.get("captures") if isinstance(store, Mapping) else None
    if not isinstance(captures, list):
        return None
    for capture in reversed(captures):
        workspace_value = capture.get("workspace_path") if isinstance(capture, Mapping) else None
        workspace = Path(workspace_value) if isinstance(workspace_value, str) else None
        if (
            isinstance(capture, Mapping)
            and capture.get("status") == "active"
            and isinstance(capture.get("reference"), str)
            and workspace is not None
            and (workspace / ".rote" / "workspace.db").is_file()
        ):
            return str(capture["reference"])
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-journey", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "worker",
        "refresh",
        "rebuild",
        "snapshot",
        "graph",
        "story",
        "scene",
        "doctor",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--capture", required=True)
        command.add_argument("--json", action="store_true")
        if name == "worker":
            command.add_argument("--once", action="store_true")
            command.add_argument("--idle-seconds", type=int, default=DEFAULT_IDLE_SECONDS)
    view = subparsers.add_parser("view")
    view_target = view.add_mutually_exclusive_group(required=True)
    view_target.add_argument("--capture")
    view_target.add_argument("--active", action="store_true")
    view.add_argument("--no-open", action="store_true")
    view.add_argument("--port", type=int)
    view.add_argument("--json", action="store_true")
    serve = subparsers.add_parser("serve")
    serve.add_argument("--capture", required=True)
    serve.add_argument("--viewer-token", required=True)
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--lifetime-seconds", type=int, default=8 * 60 * 60)
    serve.add_argument("--workspace-path")
    arguments = parser.parse_args(argv)
    capture_value = getattr(arguments, "capture", None)
    capture_ref = str(capture_value) if isinstance(capture_value, str) else ""
    active_capture: Mapping[str, Any] | None = None
    if arguments.command == "view" and bool(arguments.active):
        from .journey_view_catalog import _active_workspace_capture

        active_capture = _active_workspace_capture()
        capture_ref = str(active_capture.get("reference") or "") if active_capture else ""
        if not capture_ref or active_capture is None:
            parser.error("there is no current Rote workspace to visualize")
    if arguments.command == "serve":
        from .journey_view import serve_viewer

        return serve_viewer(
            capture_ref,
            str(arguments.viewer_token),
            port=max(0, int(arguments.port)),
            lifetime_seconds=max(1, int(arguments.lifetime_seconds)),
            workspace_path=str(arguments.workspace_path) if arguments.workspace_path else None,
        )
    if arguments.command == "view":
        from .journey_view import DEFAULT_VIEWER_PORT, JourneyViewError, launch_viewer

        try:
            configured_port = arguments.port
            if configured_port is None:
                try:
                    configured_port = int(
                        os.environ.get("PLAY_JOURNEY_PORT", str(DEFAULT_VIEWER_PORT))
                    )
                except ValueError as error:
                    raise JourneyViewError("PLAY_JOURNEY_PORT must be an integer") from error
            if configured_port < 1 or configured_port > 65535:
                raise JourneyViewError("Journey viewer port must be between 1 and 65535")
            payload = launch_viewer(
                capture_ref,
                capture=active_capture,
                open_browser=not bool(arguments.no_open),
                port=configured_port,
            )
        except JourneyViewError as error:
            parser.exit(1, f"play-journey: {error}\n")
        if arguments.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Play Journey map: {payload['url']}")
        return 0
    if arguments.command == "worker":
        return run_worker(
            capture_ref,
            once=bool(arguments.once),
            idle_seconds=max(1, int(arguments.idle_seconds)),
        )
    if arguments.command in {"refresh", "rebuild"}:
        capture = _capture(capture_ref)
        if capture is None:
            parser.error("capture is missing or expired")
        snapshot = refresh_capture(capture, force=arguments.command == "rebuild")
        if snapshot is None:
            return 1
        print(json.dumps(snapshot, indent=2, sort_keys=True) if arguments.json else render_snapshot(snapshot))
        return 0
    if arguments.command == "snapshot":
        snapshot = load_snapshot(capture_ref)
        if snapshot is None:
            return 1
        print(json.dumps(snapshot, indent=2, sort_keys=True) if arguments.json else render_snapshot(snapshot))
        return 0
    if arguments.command == "graph":
        graph = load_graph(capture_ref)
        if graph is None:
            return 1
        if arguments.json:
            print(json.dumps(graph, indent=2, sort_keys=True))
        else:
            print(
                f"Complete Journey: {len(graph.get('nodes', []))} semantic nodes · "
                f"{len(graph.get('edges', []))} edges\n"
                "Use --json for the complete evidence-linked graph."
            )
        return 0
    if arguments.command == "scene":
        from .journey_scene import build_scene

        graph = load_graph(capture_ref)
        if graph is None:
            return 1
        scene = build_scene(graph)
        if arguments.json:
            print(json.dumps(scene, indent=2, sort_keys=True))
        else:
            print(
                f"Journey scene: {len(scene.get('nodes', []))} isometric sites · "
                f"{len(scene.get('edges', []))} routed paths · "
                f"{scene['scene_sha256']}"
            )
        return 0
    if arguments.command == "story":
        from .journey_story import build_story

        graph = load_graph(capture_ref)
        if graph is None:
            return 1
        story = build_story(graph)
        if arguments.json:
            print(json.dumps(story, indent=2, sort_keys=True))
        else:
            print(
                f"Journey story: {len(story.get('chapters', []))} human landmarks · "
                f"{story['audit']['canonical_nodes']} canonical nodes preserved · "
                f"{story['story_sha256']}"
            )
        return 0
    payload = doctor(capture_ref)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
