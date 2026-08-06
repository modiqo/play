"""Typed, fail-closed handoff packets for delegated Play exploration."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from .digest_state import stable_sha


PACKET_SCHEMA = "play.handoff/v1"
RECEIPT_SCHEMA = "play.handoff-receipt/v1"
SPECIALIST_OWNERS = (
    "rote-using-adapters",
    "rote-shell",
    "rote-browse",
    "rote-workspace",
)
EXPECTED_EVENTS = {
    "outcome_ready": (
        "result_ref",
        "response_refs",
        "artifact_refs",
        "modalities_used",
        "effects",
        "route_provenance",
    ),
    "route_exhausted": ("reason", "evidence_refs"),
    "confirmation_required": ("effect_confirmation",),
}


def capability_policy(owner: str, modalities: Sequence[str]) -> dict[str, Any]:
    """Declare how a Rote-owned route must converge before it may execute."""

    if "call" in modalities:
        return {
            "kind": "rote_adapter",
            "require_rote_adapter": True,
            "discovery_order": ["installed", "catalog", "provided_spec", "provider_docs"],
            "type_selection": "auto",
            "substrate_detection": ["openapi", "graphql", "mcp"],
            "create_owner": "rote-adapter-create",
            "configure_owner": "rote-adapter-config",
            "orchestration_owner": owner,
            "adapter_execute_owner": "rote-using-adapters",
            "auth_cycle": {
                "required": True,
                "human_gate": True,
                "secret_entry": "masked",
                "completion": ["verified", "completed"],
            },
            "direct_tool_policy": "metadata_discovery_only_never_execute",
        }
    return {
        "kind": "rote_native",
        "orchestration_owner": owner,
        "direct_tool_policy": "never_execute",
    }


class HandoffError(ValueError):
    """A handoff input is malformed or violates delegated ownership."""


def owner_for_modalities(modalities: Sequence[str]) -> str:
    selected = tuple(sorted(set(modalities)))
    if not selected or len(selected) != len(modalities):
        raise HandoffError("modalities must be a non-empty unique list")
    unknown = set(selected) - {"call", "shell", "drive"}
    if unknown:
        raise HandoffError(f"unknown modalities: {', '.join(sorted(unknown))}")
    if len(selected) > 1:
        return "rote-workspace"
    return {
        "call": "rote-using-adapters",
        "shell": "rote-shell",
        "drive": "rote-browse",
    }[selected[0]]


def _string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise HandoffError(f"{field} must be a non-empty string")
    return value


def _object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise HandoffError(f"{field} must be an object")
    return value


def _string_list(payload: dict[str, Any], field: str, *, allow_empty: bool = True) -> list[str]:
    value = payload.get(field)
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
        or (not allow_empty and not value)
    ):
        suffix = "non-empty " if not allow_empty else ""
        raise HandoffError(f"{field} must be a {suffix}unique string list")
    return value


def prepare_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a packet only when its exact Rote specialist is currently callable."""

    run_id = _string(payload, "run_id")
    requested_outcome = _string(payload, "requested_outcome")
    selected_owner = _string(payload, "owner")
    modalities = _string_list(payload, "modalities", allow_empty=False)
    available_owners = _string_list(payload, "available_owners")
    expected_owner = owner_for_modalities(modalities)
    if selected_owner != expected_owner:
        reason = (
            f"route {','.join(modalities)} requires {expected_owner}; "
            f"selected owner was {selected_owner}"
        )
        return {
            "schema": "play.handoff-preparation/v1",
            "ok": False,
            "event": "specialist_unavailable",
            "available": False,
            "reason": reason,
            "blocked_reason": reason,
            "required_owner": expected_owner,
            "available_owners": sorted(set(available_owners)),
        }
    if selected_owner not in available_owners:
        reason = f"required Rote specialist {selected_owner} is not callable in this harness"
        return {
            "schema": "play.handoff-preparation/v1",
            "ok": False,
            "event": "specialist_unavailable",
            "available": False,
            "reason": reason,
            "blocked_reason": reason,
            "required_owner": selected_owner,
            "available_owners": sorted(set(available_owners)),
        }

    packet = {
        "schema": PACKET_SCHEMA,
        "run_id": run_id,
        "state": "explore_execute",
        "action": "execute_route",
        "owner": selected_owner,
        "requested_outcome": requested_outcome,
        "modalities": modalities,
        "constraints": _object(payload, "constraints"),
        "inputs": _object(payload, "inputs"),
        "capability_policy": capability_policy(selected_owner, modalities),
        "expected_events": {key: list(value) for key, value in EXPECTED_EVENTS.items()},
        "effect_policy": _object(payload, "effect_policy"),
        "evidence_contract": _string_list(payload, "evidence_contract"),
        "idempotency_key": _string(payload, "idempotency_key"),
    }
    packet_sha256 = stable_sha(packet)
    return {
        "schema": "play.handoff-preparation/v1",
        "ok": True,
        "event": "specialist_handoff_ready",
        "available": True,
        "owner": selected_owner,
        "packet": packet,
        "packet_sha256": packet_sha256,
        "expected_events": sorted(EXPECTED_EVENTS),
    }


def _invalid_receipt(*reasons: str) -> dict[str, Any]:
    return {
        "schema": "play.handoff-verification/v1",
        "ok": False,
        "event": "specialist_receipt_invalid",
        "receipt_valid": False,
        "blocked_reason": "; ".join(reasons),
        "evidence_refs": [],
        "reasons": list(reasons),
    }


def _validate_route_provenance(
    provenance: Any, *, owner: Any, modalities: Sequence[str]
) -> list[str]:
    if not isinstance(provenance, dict):
        return ["receipt route_provenance must be an object"]
    reasons: list[str] = []
    if provenance.get("direct_tool_execution") is not False:
        reasons.append("route provenance must prove direct_tool_execution is false")
    evidence_refs = provenance.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) or not item for item in evidence_refs)
    ):
        reasons.append("route provenance requires non-empty evidence_refs")

    if "call" not in modalities:
        if provenance.get("kind") != "rote_native":
            reasons.append("non-CALL route provenance kind must be rote_native")
        if provenance.get("orchestration_owner") != owner:
            reasons.append("route provenance orchestration_owner does not match packet owner")
        return reasons

    if provenance.get("kind") != "rote_adapter":
        reasons.append("CALL route provenance kind must be rote_adapter")
    if provenance.get("orchestration_owner") != owner:
        reasons.append("adapter provenance orchestration_owner does not match packet owner")
    if provenance.get("adapter_execute_owner") != "rote-using-adapters":
        reasons.append("CALL must execute through rote-using-adapters")
    adapter_id = provenance.get("adapter_id")
    if not isinstance(adapter_id, str) or not adapter_id:
        reasons.append("adapter provenance requires adapter_id")
    if provenance.get("substrate") not in {"openapi", "graphql", "mcp"}:
        reasons.append("adapter substrate must be openapi, graphql, or mcp")
    type_evidence_ref = provenance.get("type_evidence_ref")
    if not isinstance(type_evidence_ref, str) or not type_evidence_ref:
        reasons.append("adapter provenance requires type_evidence_ref")
    adapter_status = provenance.get("adapter_status")
    creation_owner = provenance.get("creation_owner")
    if adapter_status == "created":
        if creation_owner != "rote-adapter-create":
            reasons.append("created adapters require rote-adapter-create provenance")
    elif adapter_status == "reused":
        if creation_owner is not None:
            reasons.append("reused adapters must not claim a creation owner")
    else:
        reasons.append("adapter_status must be created or reused")
    auth_status = provenance.get("auth_status")
    auth_owner = provenance.get("auth_owner")
    if auth_status == "completed":
        if auth_owner not in {"rote-adapter-create", "rote-adapter-config"}:
            reasons.append("completed auth requires a Rote create/config owner")
    elif auth_status == "verified":
        if auth_owner not in {
            "rote-using-adapters",
            "rote-adapter-create",
            "rote-adapter-config",
        }:
            reasons.append("verified auth requires a recognized Rote adapter owner")
    else:
        reasons.append("auth_status must be verified or completed")
    return reasons


def _validate_effect_confirmation(confirmation: Any) -> list[str]:
    if not isinstance(confirmation, dict):
        return ["receipt effect_confirmation must be an object"]
    reasons: list[str] = []
    if confirmation.get("source") != "rote_confirmation_required":
        reasons.append("effect confirmation source must be rote_confirmation_required")
    if confirmation.get("status") != "required":
        reasons.append("effect confirmation status must be required")
    for field in ("tool", "impact", "confirm_token", "workspace"):
        value = confirmation.get(field)
        if not isinstance(value, str) or not value:
            reasons.append(f"effect confirmation requires non-empty {field}")
    evidence_refs = confirmation.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) or not item for item in evidence_refs)
    ):
        reasons.append("effect confirmation requires non-empty evidence_refs")
    return reasons


def verify_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate that a specialist receipt belongs to the exact prepared handoff."""

    packet = payload.get("packet")
    receipt = payload.get("receipt")
    if not isinstance(packet, dict) or not isinstance(receipt, dict):
        return _invalid_receipt("packet and receipt must be objects")
    if packet.get("schema") != PACKET_SCHEMA:
        return _invalid_receipt(f"packet must use {PACKET_SCHEMA}")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return _invalid_receipt(f"receipt must use {RECEIPT_SCHEMA}")

    reasons: list[str] = []
    if packet.get("state") != "explore_execute":
        reasons.append("packet state must be explore_execute")
    if packet.get("action") != "execute_route":
        reasons.append("packet action must be execute_route")
    owner = packet.get("owner")
    if owner not in SPECIALIST_OWNERS:
        reasons.append("packet owner is not a recognized Rote specialist")
    modalities = packet.get("modalities")
    if not isinstance(modalities, list) or any(not isinstance(item, str) for item in modalities):
        reasons.append("packet modalities must be a string list")
    else:
        try:
            expected_owner = owner_for_modalities(modalities)
        except HandoffError as error:
            reasons.append(str(error))
        else:
            if owner != expected_owner:
                reasons.append("packet owner does not match its modalities")
        expected_policy = capability_policy(owner, modalities)
        if packet.get("capability_policy") != expected_policy:
            reasons.append("packet capability policy differs from the closed Rote contract")
    if packet.get("expected_events") != {
        key: list(value) for key, value in EXPECTED_EVENTS.items()
    }:
        reasons.append("packet expected events differ from the closed action contract")
    packet_sha256 = stable_sha(packet)
    if receipt.get("packet_sha256") != packet_sha256:
        reasons.append("receipt packet hash does not match")
    for field in ("run_id", "state", "action", "owner"):
        if receipt.get(field) != packet.get(field):
            reasons.append(f"receipt {field} does not match packet")
    executor = receipt.get("executor")
    if not isinstance(executor, dict):
        reasons.append("receipt executor is missing")
    else:
        if executor.get("kind") != "skill":
            reasons.append("receipt executor kind must be skill")
        if executor.get("name") != packet.get("owner"):
            reasons.append("receipt executor name does not match owner")

    event = receipt.get("event")
    expected_events = packet.get("expected_events")
    required_fields = (
        expected_events.get(event)
        if isinstance(expected_events, dict) and isinstance(event, str)
        else None
    )
    if not isinstance(event, str) or not isinstance(required_fields, list):
        reasons.append("receipt event is not declared by the packet")
    result_payload = receipt.get("payload")
    if not isinstance(result_payload, dict):
        reasons.append("receipt payload must be an object")
    elif isinstance(required_fields, list):
        missing = [field for field in required_fields if field not in result_payload]
        if missing:
            reasons.append(f"receipt payload is missing: {', '.join(missing)}")
        if event == "outcome_ready" and isinstance(modalities, list):
            reasons.extend(
                _validate_route_provenance(
                    result_payload.get("route_provenance"),
                    owner=owner,
                    modalities=modalities,
                )
            )
        elif event == "confirmation_required":
            reasons.extend(
                _validate_effect_confirmation(result_payload.get("effect_confirmation"))
            )
    evidence_refs = receipt.get("evidence_refs")
    if not isinstance(evidence_refs, list) or any(not isinstance(item, str) for item in evidence_refs):
        reasons.append("receipt evidence_refs must be a string list")
    if reasons:
        return _invalid_receipt(*reasons)

    return {
        **result_payload,
        "schema": "play.handoff-verification/v1",
        "ok": True,
        "event": {
            "outcome_ready": "specialist_outcome_ready",
            "route_exhausted": "specialist_route_exhausted",
            "confirmation_required": "specialist_confirmation_required",
        }[event],
        "owner": packet["owner"],
        "packet_sha256": packet_sha256,
        "receipt_ref": stable_sha(receipt),
        "receipt_valid": True,
        "evidence_refs": evidence_refs,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="play-handoff", description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--stdin", action="store_true", required=True, help="Read one JSON object")
    parser.add_argument("--json", action="store_true", required=True, help="Emit one JSON object")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise HandoffError("input must be a JSON object")
        result = prepare_handoff(payload) if args.command == "prepare" else verify_receipt(payload)
    except (HandoffError, json.JSONDecodeError) as error:
        print(f"play-handoff: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
