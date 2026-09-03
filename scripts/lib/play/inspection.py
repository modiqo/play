"""Read-only Play inspection normalized for disclose-before-run approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from .registry import PlayNotFoundError, RegistryReadError, load_play_inspection
from .render import json_text


def attach_report_card(disclosure: dict[str, Any], reference: str) -> None:
    """Append the advisory audit card. Never raises; never blocks the disclosure."""
    try:
        from .audit import card
        from .audit.cli import audit_target

        envelope = audit_target(reference)
        text = card(envelope)
        if text:
            disclosure["audit_card"] = text
            disclosure["audit_summary"] = envelope.get("summary")
    except BaseException:  # noqa: BLE001 - advisory by contract
        return


SCHEMA = "play.run-disclosure/v1"


class InspectionError(RegistryReadError):
    pass


def _objects(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _canonical_reference(identity: dict[str, Any]) -> str:
    owner = identity.get("owner")
    name = identity.get("name")
    version = identity.get("version")
    if not isinstance(owner, str) or not isinstance(name, str):
        raise InspectionError("Play inspection lacks a canonical owner and name")
    return f"{owner}/{name}@{version}" if isinstance(version, str) and version else f"{owner}/{name}"


def _parameters(raw: object) -> list[dict[str, Any]]:
    parameters = []
    for item in _objects(raw):
        name = item.get("name")
        if not isinstance(name, str):
            continue
        normalized = {
            "name": name,
            "label": name,
            "type": item.get("type") if isinstance(item.get("type"), str) else "unknown",
            "required": item.get("required") is True,
            "description": item.get("description") or "",
            "example": item.get("example"),
            "valid_values": _items(item.get("valid_values")),
            "has_default": "default" in item,
            "default": item.get("default"),
        }
        input_spec = item.get("input")
        if isinstance(input_spec, dict):
            normalized["label"] = input_spec.get("label") or name
            normalized["allow_custom"] = input_spec.get("allow_custom") is True
            normalized["choices"] = _objects(input_spec.get("choices"))
        parameters.append(normalized)
    return parameters


def _operations(raw: object) -> list[dict[str, Any]]:
    operations = []
    for item in _objects(raw):
        name = item.get("name")
        if not isinstance(name, str):
            continue
        operations.append(
            {
                "name": name,
                "target": item.get("target") if isinstance(item.get("target"), str) else None,
                "operation": (
                    item.get("operation") if isinstance(item.get("operation"), str) else None
                ),
                "endpoint": (
                    item.get("endpoint") if isinstance(item.get("endpoint"), str) else None
                ),
                "method": item.get("method") if isinstance(item.get("method"), str) else None,
                "depends_on": _strings(item.get("depends_on")),
            }
        )
    return operations


def _adapter_checks(convergence: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    for item in _objects(convergence.get("adapters")):
        demand = item.get("credential_demand")
        checks.append(
            {
                "adapter_id": item.get("adapter_id"),
                "requirement": item.get("requirement"),
                "local_state": item.get("local_state"),
                "decision": item.get("decision"),
                "reason": item.get("reason"),
                "user_action": item.get("user_action"),
                "credential_demand": (
                    {
                        "status": demand.get("status"),
                        "names": _strings(demand.get("names")),
                        "protocols": _strings(demand.get("protocols")),
                    }
                    if isinstance(demand, dict)
                    else {"status": "unknown", "names": [], "protocols": []}
                ),
            }
        )
    return checks


def normalize_inspection(requested_reference: str, inspected: dict[str, Any]) -> dict[str, Any]:
    identity = inspected.get("identity")
    execution = inspected.get("execution")
    requirements = inspected.get("requirements")
    host = inspected.get("host")
    convergence = inspected.get("convergence")
    archive = inspected.get("archive")
    if not all(
        isinstance(item, dict)
        for item in (identity, execution, requirements, host, convergence, archive)
    ):
        raise InspectionError("Play inspection is missing identity, execution, or preflight data")

    exact_reference = _canonical_reference(identity)
    play_check = convergence.get("play")
    if not isinstance(play_check, dict):
        play_check = {}
    decision = play_check.get("decision")
    local_state = play_check.get("local_state")
    local_change = {
        "install_required": "install",
        "repair_required": "replace_or_restore",
        "ready": "none",
    }.get(decision, "unknown")
    write_permissions = _items(requirements.get("write_permissions"))
    operations = _operations(inspected.get("steps"))
    if write_permissions:
        effect_certainty = "writes_declared"
        effect_summary = "The manifest declares write permissions; review them before approval."
    elif operations:
        effect_certainty = "operation_semantics_unknown"
        effect_summary = (
            "No write permissions are declared, but generic adapter operations do not prove "
            "that external activity is read-only."
        )
    else:
        effect_certainty = "operations_undeclared"
        effect_summary = "The manifest declares no steps, so read/write operations cannot be verified."

    blockers = _strings(execution.get("blockers"))
    run_eligible = execution.get("play_run_eligible") is True and not blockers
    disclosure = {
        "schema": SCHEMA,
        "complete": True,
        "requested_reference": requested_reference,
        "exact_reference": exact_reference,
        "description": identity.get("description") or "",
        "local_change": local_change,
        "blockers": blockers,
        "identity": {
            "owner": identity.get("owner"),
            "name": identity.get("name"),
            "version": identity.get("version"),
            "description": identity.get("description") or "",
            "visibility": identity.get("visibility"),
            "content_hash": archive.get("content_hash"),
        },
        "parameters": _parameters(inspected.get("parameters")),
        "operations": operations,
        "dependencies": {
            "services": _items(requirements.get("endpoints")),
            "runtimes": _items(requirements.get("runtimes")),
            "npm_packages": _items(requirements.get("npm_packages")),
            "browser_binaries": _items(requirements.get("browser_binaries")),
            "browser_auth": requirements.get("browser_auth"),
            "adapter_credentials": requirements.get("adapter_credentials"),
            "adapter_checks": _adapter_checks(convergence),
            "sensitivity": requirements.get("sensitivity"),
        },
        "effects": {
            "classification": effect_certainty,
            "summary": effect_summary,
            "declared_write_permissions": write_permissions,
        },
        "preflight": {
            "read_only": convergence.get("read_only") is True,
            "run_eligible": run_eligible,
            "blockers": blockers,
            "play_local_state": local_state,
            "decision": decision,
            "local_change": local_change,
            "pull_or_install_required": local_change in {"install", "replace_or_restore"},
            "reason": play_check.get("reason"),
            "user_action": play_check.get("user_action"),
            "host": host,
            "unsupported": _objects(convergence.get("unsupported")),
        },
        "approval": {
            "required": True,
            "allowed": run_eligible,
            "scope": exact_reference,
            "notice": "Inspection is read-only. Nothing has been installed, changed, or run.",
        },
    }
    digest_source = json.dumps(disclosure, sort_keys=True, separators=(",", ":"))
    disclosure["disclosure_sha256"] = hashlib.sha256(digest_source.encode()).hexdigest()
    return disclosure


def inspect_for_run(reference: str) -> dict[str, Any]:
    return normalize_inspection(reference, load_play_inspection(reference))


def render_markdown(disclosure: dict[str, Any]) -> str:
    identity = disclosure["identity"]
    preflight = disclosure["preflight"]
    dependencies = disclosure["dependencies"]
    effects = disclosure["effects"]
    lines = [
        f"# {identity['name']}",
        "",
        identity["description"] or "No description provided.",
        "",
        f"Reference: `{disclosure['exact_reference']}` · {identity['visibility']}",
    ]
    base_reference = str(disclosure["exact_reference"]).rsplit("@", 1)[0]
    if "/" in base_reference:
        lines.append(
            f"Play card: https://play.modiqo.ai/{base_reference}"
        )
    lines += [
        "",
        "## Setup on this machine",
        "",
        f"- Play: {preflight['play_local_state']} ({preflight['decision']})",
    ]
    if preflight.get("reason"):
        lines.append(f"- {preflight['reason']}")
    for check in dependencies["adapter_checks"]:
        credential = check["credential_demand"]
        names = ", ".join(credential["names"]) or "unspecified credential"
        lines.append(
            f"- Adapter `{check['adapter_id']}`: {check['local_state']}; "
            f"credentials {credential['status']} ({names})"
        )
    lines.extend(["", "## Operations and effects", ""])
    if disclosure["operations"]:
        for operation in disclosure["operations"]:
            target = operation["endpoint"] or operation["target"] or "unspecified target"
            lines.append(f"- `{operation['name']}`: {operation['operation'] or 'unknown'} via `{target}`")
    else:
        lines.append("- No steps are declared in the manifest.")
    lines.append(f"- {effects['summary']}")
    lines.extend(["", "## Parameters", ""])
    if disclosure["parameters"]:
        for parameter in disclosure["parameters"]:
            default = f"; default `{parameter['default']}`" if parameter["has_default"] else ""
            requirement = "required" if parameter["required"] else "optional"
            lines.append(f"- `{parameter['name']}`: {parameter['type']} ({requirement}{default})")
    else:
        lines.append("- None declared.")
    lines.extend(["", "## Ready to run", ""])
    if preflight["run_eligible"]:
        lines.append("Eligible after explicit approval of the exact reference and displayed parameters.")
    else:
        lines.append("Not runnable: " + ("; ".join(preflight["blockers"]) or "preflight failed"))
    if disclosure.get("audit_card"):
        lines.extend(["", "## Before you run", "", "```text", str(disclosure["audit_card"]), "```"])
    lines.extend(["", disclosure["approval"]["notice"]])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--card", action="store_true", default=True, help="append the advisory audit report card (default)")
    parser.add_argument("--no-card", action="store_false", dest="card", help="skip the advisory audit report card")
    args = parser.parse_args()
    try:
        disclosure = inspect_for_run(args.reference)
        if args.card:
            attach_report_card(disclosure, args.reference)
    except RegistryReadError as error:
        if args.as_json:
            print(
                json_text(
                    {
                        "schema": SCHEMA,
                        "complete": False,
                        "requested_reference": args.reference,
                        "error": {
                            "kind": (
                                "play_not_found"
                                if isinstance(error, PlayNotFoundError)
                                else "inspection_failed"
                            ),
                            "message": str(error),
                        },
                    }
                )
            )
        else:
            print(f"play-inspect: {error}", file=sys.stderr)
        return 1
    print(json_text(disclosure) if args.as_json else render_markdown(disclosure))
    return 0
