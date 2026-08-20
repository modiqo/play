"""Deterministic Rote capability taxonomy for Play Journey projections.

The Journey worker calls this module off the foreground path.  Descriptors are
safe, compact metadata: they identify the execution substrate without copying
command arguments, response payloads, credentials, or adapter configuration.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


SCHEMA = "play.journey-capability/v1"

_ADAPTER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_ADAPTER_ENDPOINT = re.compile(r"^/?adapter/(?P<adapter_id>[a-z0-9][a-z0-9_-]{0,127})$")
_BROWSER_ENDPOINT = re.compile(r"^stdio:/(?:.*playwright|browser)", re.IGNORECASE)
_PACKAGE_RUNNERS = {"bunx", "npx"}

# This is Rote's adapter MCP grammar, not a semantic keyword list. Every
# generated adapter exposes these wrappers; the concrete API operations are
# carried inside their typed arguments.
_ADAPTER_ENVELOPES = (
    ("batch_call", "call", "batch"),
    ("probe_call", "call", "probe-discovered"),
    ("probe", "probe", "single"),
    ("call", "call", "single"),
)


def _safe_string(value: object, *, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:limit]
    return text or None


def _rote_home() -> Path:
    override = os.environ.get("ROTE_HOME")
    return Path(override) if override else Path.home() / ".rote"


def _manifest_transport(spec_type: str | None) -> str:
    value = (spec_type or "").lower()
    if value == "mcp":
        return "mcp"
    if value == "grpc":
        return "grpc"
    if value in {"data", "json", "jsonpath"}:
        return "local data"
    if value == "stdio":
        return "stdio"
    return "http"


@lru_cache(maxsize=256)
def adapter_manifest_summary(adapter_id: str) -> dict[str, Any] | None:
    """Read one bounded, non-secret manifest summary for the async projector."""

    if not _ADAPTER_ID.fullmatch(adapter_id):
        return None
    path = _rote_home() / "adapters" / adapter_id / "manifest.json"
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    auth = value.get("auth")
    auth = auth if isinstance(auth, Mapping) else {}
    spec_type = _safe_string(value.get("spec_type")) or "adapter"
    schema_value = value.get("schema")
    schema = schema_value if isinstance(schema_value, int) and schema_value > 0 else 1
    summary = {
        "schema": schema,
        "name": _safe_string(value.get("name")) or adapter_id,
        "spec_type": spec_type,
        "spec_version": _safe_string(value.get("spec_version")),
        "transport": _manifest_transport(spec_type),
        "auth_type": _safe_string(auth.get("type")),
        "operation_scope": _safe_string(value.get("operation_scope")),
        "fingerprint": _safe_string(value.get("fingerprint")),
        "status": _safe_string(value.get("status")),
    }
    return {key: item for key, item in summary.items() if item is not None}


def _browser_action(payload: Mapping[str, Any]) -> str | None:
    """Return one allowlisted browser action without retaining arguments."""

    body = payload.get("body")
    body = body if isinstance(body, Mapping) else {}
    params = body.get("params")
    params = params if isinstance(params, Mapping) else {}
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, Mapping) else {}
    action = arguments.get("action")
    if not isinstance(action, str):
        return None
    value = action.lower().replace("-", "_")
    return value if value in {"list", "new", "select", "activate", "close"} else None


def _browser_primitive(
    operation: str,
    payload: Mapping[str, Any],
    browser_record: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    value = operation.lower().replace("-", "_")
    record_kind = str((browser_record or {}).get("kind") or "")
    if record_kind == "authority":
        return "authority", "Browser authority"
    if record_kind == "blocker":
        return "ledger", "Browser capture"
    if record_kind == "wait":
        return "wait", "Browser wait"
    if record_kind in {"snapshot", "assertion"}:
        return "ledger", "Page observation"
    if record_kind == "action":
        return "action", "Browser action"
    action = _browser_action(payload)
    if "tabs" in value and action == "list":
        return "inventory", "Tab inventory"
    if "tabs" in value or "lease" in value or value == "initialize":
        return "lease", "Page lease"
    if (
        "snapshot" in value
        or "screenshot" in value
        or "ledger" in value
        or "history" in value
    ):
        return "ledger", "Page ledger"
    if "slice" in value:
        return "slice", "Snapshot slice"
    if "rebase" in value or "lens" in value:
        return "lens", "Evidence lens"
    if "wait" in value:
        return "wait", "Browser wait"
    if "navigate" in value:
        return "navigate", "Browser navigation"
    return "action", "Browser action"


def _process_mode(command_type: str) -> str:
    return {
        "ProcessPtyRun": "pty",
        "ProcessBackgroundStart": "background",
        "ProcessBackgroundStatus": "lease status",
        "ProcessBackgroundWait": "lease wait",
        "ProcessBackgroundStop": "lease stop",
        "StreamFollow": "stream",
    }.get(command_type, "argv")


def _process_cli(payload: Mapping[str, Any]) -> str:
    invocation = payload.get("invocation")
    invocation = invocation if isinstance(invocation, Mapping) else payload
    program = Path(str(invocation.get("program") or "process")).name
    arguments = invocation.get("args")
    arguments = arguments if isinstance(arguments, list) else []
    values = [value for value in arguments if isinstance(value, str)]
    if program in _PACKAGE_RUNNERS:
        candidate = next((value for value in values if not value.startswith("-")), None)
        return Path(candidate).name if candidate else program
    if program in {"npm", "pnpm", "yarn"} and values:
        start = 1 if values[0] in {"exec", "dlx"} else 0
        candidate = next((value for value in values[start:] if not value.startswith("-")), None)
        return Path(candidate).name if candidate else program
    return program


def _adapter_operations(
    envelope: str,
    arguments: Mapping[str, Any],
) -> list[str]:
    """Extract operation names from one validated Rote adapter envelope."""

    if envelope == "batch_call":
        calls = arguments.get("calls")
        calls = calls if isinstance(calls, list) else []
        return [
            tool
            for call in calls
            if isinstance(call, Mapping)
            for tool in [_safe_string(call.get("tool_name"))]
            if tool
        ]
    field = "name" if envelope == "probe_call" else "tool_name"
    tool = _safe_string(arguments.get(field))
    return [tool] if tool else []


def adapter_invocation(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse Rote's canonical ``adapter/<id>`` MCP request grammar.

    The endpoint establishes adapter ownership. The MCP envelope establishes
    whether this interaction discovers operations or executes them. We never
    infer adapter use from a display label, a generic provider field, or words
    found in user-controlled arguments.
    """

    endpoint = _safe_string(payload.get("endpoint")) or ""
    match = _ADAPTER_ENDPOINT.fullmatch(endpoint)
    if match is None:
        return None
    adapter_id = match.group("adapter_id")
    body = payload.get("body")
    template_present = isinstance(payload.get("body_template"), str)
    if not isinstance(body, Mapping):
        template = payload.get("body_template")
        if isinstance(template, str):
            try:
                body = json.loads(template)
            except json.JSONDecodeError:
                body = None
    body = body if isinstance(body, Mapping) else {}
    method = _safe_string(body.get("method")) or ""
    if method != "tools/call":
        if template_present:
            return {
                "adapter_id": adapter_id,
                "phase": "call",
                "mode": "iteration",
                "wrapper": None,
                "operations": [],
            }
        return {
            "adapter_id": adapter_id,
            "phase": "protocol",
            "mode": method or "protocol",
            "wrapper": None,
            "operations": [],
        }
    params = body.get("params")
    params = params if isinstance(params, Mapping) else {}
    wrapper = _safe_string(params.get("name")) or ""
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, Mapping) else {}
    prefix = adapter_id.replace("-", "_")
    envelope = next(
        (
            (suffix, phase, mode)
            for suffix, phase, mode in _ADAPTER_ENVELOPES
            if wrapper == f"{prefix}_{suffix}"
        ),
        None,
    )
    if envelope is None:
        # Native MCP adapters may expose direct tools rather than Rote's
        # generated wrapper triple. It is still an adapter call because both
        # the canonical endpoint and tools/call wire contract are present.
        return {
            "adapter_id": adapter_id,
            "phase": "call",
            "mode": "native",
            "wrapper": wrapper or None,
            "operations": [wrapper] if wrapper else [],
        }
    suffix, phase, mode = envelope
    return {
        "adapter_id": adapter_id,
        "phase": phase,
        "mode": mode,
        "wrapper": wrapper,
        "envelope": suffix,
        "operations": _adapter_operations(suffix, arguments),
    }


def capability_descriptor(
    command_type: str,
    payload: Mapping[str, Any],
    operation: str,
    provider: str | None,
    *,
    manifest_resolver: Callable[[str], Mapping[str, Any] | None] | None = None,
    browser_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the Rote execution substrate without semantic guesswork."""

    endpoint = str(payload.get("endpoint") or "")
    endpoint_match = _ADAPTER_ENDPOINT.fullmatch(endpoint)
    if command_type == "InitSession" and _BROWSER_ENDPOINT.search(endpoint):
        return {
            "schema": SCHEMA,
            "family": "browser",
            "interface": "browse",
            "id": "browser:lease",
            "label": "Browser session",
            "primitive": "lease",
            "phase": "initialize",
            "tool": "initialize",
            "transport": "stdio",
        }
    if command_type == "InitSession" and endpoint_match is not None:
        adapter_id = endpoint_match.group("adapter_id")
        resolver = manifest_resolver or (lambda _adapter_id: None)
        manifest = resolver(adapter_id)
        manifest = dict(manifest) if isinstance(manifest, Mapping) else {}
        descriptor: dict[str, Any] = {
            "schema": SCHEMA,
            "family": "adapter",
            "interface": "api",
            "id": adapter_id,
            "label": str(manifest.get("name") or adapter_id),
            "phase": "initialize",
            "mode": "session",
            "tool": "initialize",
            "operations": [],
            "transport": str(manifest.get("transport") or "adapter"),
        }
        if manifest:
            descriptor["manifest"] = manifest
        return descriptor
    if command_type == "HttpRequest" and (
        _BROWSER_ENDPOINT.search(endpoint) or operation.startswith("browser_")
    ):
        primitive, label = _browser_primitive(operation, payload, browser_record)
        descriptor = {
            "schema": SCHEMA,
            "family": "browser",
            "interface": "browse",
            "id": f"browser:{primitive}",
            "label": label,
            "primitive": primitive,
            "tool": operation,
            "transport": "stdio",
        }
        action = _browser_action(payload)
        if action is not None:
            descriptor["action"] = action
        record_kind = (browser_record or {}).get("kind")
        if isinstance(record_kind, str):
            descriptor["record_kind"] = record_kind
        return descriptor

    adapter = (
        adapter_invocation(payload)
        if command_type in {"HttpRequest", "For"}
        else None
    )
    if adapter is not None and adapter["phase"] != "protocol":
        adapter_id = str(adapter["adapter_id"])
        resolver = manifest_resolver or (lambda _adapter_id: None)
        manifest = resolver(adapter_id)
        manifest = dict(manifest) if isinstance(manifest, Mapping) else {}
        label = str(manifest.get("name") or adapter_id)
        operations = [str(item) for item in adapter["operations"]]
        tool = operations[0] if len(operations) == 1 else str(adapter.get("wrapper") or operation)
        descriptor: dict[str, Any] = {
            "schema": SCHEMA,
            "family": "adapter",
            "interface": "api",
            "id": adapter_id,
            "label": label,
            "phase": adapter["phase"],
            "mode": adapter["mode"],
            "wrapper": adapter.get("wrapper"),
            "tool": tool,
            "operations": operations,
            "transport": str(manifest.get("transport") or "adapter"),
        }
        if command_type == "For":
            descriptor["mode"] = (
                "parallel iteration"
                if payload.get("parallel") is True
                else "sequential iteration"
            )
        if manifest:
            descriptor["manifest"] = manifest
        return {key: value for key, value in descriptor.items() if value is not None}

    if command_type == "DataQuery":
        adapter_id = provider or str(payload.get("adapter_id") or "data")
        resolver = manifest_resolver or (lambda _adapter_id: None)
        manifest = resolver(adapter_id)
        manifest = dict(manifest) if isinstance(manifest, Mapping) else {}
        descriptor = {
            "schema": SCHEMA,
            "family": "adapter",
            "interface": "api",
            "id": adapter_id,
            "label": str(manifest.get("name") or adapter_id),
            "phase": "call",
            "mode": "data query",
            "tool": operation,
            "operations": [operation],
            "transport": "local data",
            "implementation": _safe_string(payload.get("implementation_type")),
        }
        if manifest:
            descriptor["manifest"] = manifest
        return {key: value for key, value in descriptor.items() if value is not None}

    if adapter is not None:
        adapter_id = str(adapter["adapter_id"])
        resolver = manifest_resolver or (lambda _adapter_id: None)
        manifest = resolver(adapter_id)
        manifest = dict(manifest) if isinstance(manifest, Mapping) else {}
        return {
            "schema": SCHEMA,
            "family": "adapter",
            "interface": "api",
            "id": adapter_id,
            "label": str(manifest.get("name") or adapter_id),
            "phase": "protocol",
            "mode": str(adapter["mode"]),
            "primitive": "adapter protocol",
            "tool": str(adapter["mode"]),
            "operations": [],
            "transport": str(manifest.get("transport") or "adapter"),
        }

    if command_type == "For":
        adapter_id = endpoint_match.group("adapter_id") if endpoint_match is not None else "http"
        return {
            "schema": SCHEMA,
            "family": "adapter",
            "interface": "api",
            "id": adapter_id,
            "label": adapter_id if adapter_id != "http" else "HTTP endpoint",
            "phase": "call",
            "mode": "iteration",
            "tool": operation,
            "operations": [],
            "transport": "http",
            "http_method": str(payload.get("method") or "").upper() or None,
        }

    if command_type.startswith("Process") or command_type == "StreamFollow":
        cli = _process_cli(payload)
        descriptor = {
            "schema": SCHEMA,
            "family": "proc",
            "interface": "shell",
            "id": cli,
            "label": f"{cli} CLI" if cli != "process" else "Local process",
            "tool": cli,
            "mode": _process_mode(command_type),
        }
        lease_id = payload.get("lease_id")
        if isinstance(lease_id, str) and lease_id:
            descriptor["lease_id"] = lease_id
        return descriptor

    primitive = {
        "QueryRead": "query",
        "QueryExtract": "extract",
        "Display": "display",
        "SetVariable": "variable",
        "DepsCheck": "dependency check",
        "ComposeEmail": "compose",
    }.get(command_type, "workspace")
    return {
        "schema": SCHEMA,
        "family": "rote",
        "interface": "workspace",
        "id": f"rote:{primitive}",
        "label": "Rote memory" if primitive in {"query", "extract", "display"} else "Rote workspace",
        "primitive": primitive,
        "tool": operation,
    }


def attach_browser_lenses(activities: Sequence[dict[str, Any]]) -> None:
    """Mark cached-response queries over browser results as browser lenses."""

    response_owner: dict[int, Mapping[str, Any]] = {}
    for activity in activities:
        for reference in activity.get("response_refs", []):
            if isinstance(reference, str) and reference.startswith("@"):
                try:
                    response_owner[int(reference[1:])] = activity
                except ValueError:
                    continue
    for activity in activities:
        source = activity.get("source_response")
        if not isinstance(source, int):
            continue
        owner = response_owner.get(source)
        owner_capability = owner.get("capability") if isinstance(owner, Mapping) else None
        if not isinstance(owner_capability, Mapping) or owner_capability.get("family") != "browser":
            continue
        activity["capability"] = {
            "schema": SCHEMA,
            "family": "browser",
            "interface": "browse",
            "id": "browser:lens",
            "label": "Evidence lens",
            "primitive": "lens",
            "tool": str(activity.get("operation") or "query stored evidence"),
            "transport": str(owner_capability.get("transport") or "stdio"),
        }
        activity["effect_profile"] = {
            "schema": "play.journey-effect/v1",
            "posture": "read",
            "scopes": ["browser_state"],
            "source": "browser_ledger_primitive",
            "confidence": "deterministic",
            "destructive": False,
        }
