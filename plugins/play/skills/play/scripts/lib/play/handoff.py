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
AUTH_REPAIR_PACKET_SCHEMA = "play.auth-repair-handoff/v1"
AUTH_REPAIR_RECEIPT_SCHEMA = "play.auth-repair-receipt/v1"
AUTH_REPAIR_OWNER = "rote-adapter-config"
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
    "auth_repair_required": ("auth_repair",),
}
AUTH_REPAIR_EXPECTED_EVENTS = {
    "auth_repair_ready": ("auth_repair",),
    "auth_repair_failed": ("reason", "evidence_refs"),
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

    constraints = _object(payload, "constraints")
    inputs = _object(payload, "inputs")
    effect_policy = _object(payload, "effect_policy")
    evidence_contract = _string_list(payload, "evidence_contract")
    idempotency_key = _string(payload, "idempotency_key")
    resume: dict[str, Any] | None = None
    resume_payload = payload.get("auth_repair_resume")
    if resume_payload is not None:
        if not isinstance(resume_payload, dict):
            raise HandoffError("auth_repair_resume must be an object")
        original_packet = resume_payload.get("original_packet")
        original_packet_sha256 = resume_payload.get("original_packet_sha256")
        repair_packet = resume_payload.get("repair_packet")
        repair_receipt = resume_payload.get("repair_receipt")
        repair_receipt_ref = resume_payload.get("repair_receipt_ref")
        repair_result = resume_payload.get("auth_repair")
        if not isinstance(original_packet, dict):
            raise HandoffError("auth_repair_resume original_packet must be an object")
        if original_packet.get("schema") != PACKET_SCHEMA:
            raise HandoffError(f"auth_repair_resume original_packet must use {PACKET_SCHEMA}")
        if not isinstance(original_packet_sha256, str) or not original_packet_sha256:
            raise HandoffError("auth_repair_resume original_packet_sha256 must be non-empty")
        if stable_sha(original_packet) != original_packet_sha256:
            raise HandoffError("auth_repair_resume original packet hash does not match")
        if not isinstance(repair_receipt_ref, str) or not repair_receipt_ref:
            raise HandoffError("auth_repair_resume repair_receipt_ref must be non-empty")
        verified_repair = verify_auth_repair_receipt(
            {"packet": repair_packet, "receipt": repair_receipt}
        )
        if not verified_repair.get("ok"):
            reasons = verified_repair.get("reasons", ["repair receipt is invalid"])
            raise HandoffError(f"auth_repair_resume {'; '.join(reasons)}")
        if verified_repair.get("receipt_ref") != repair_receipt_ref:
            raise HandoffError("auth_repair_resume repair receipt reference does not match")
        if verified_repair.get("auth_repair") != repair_result:
            raise HandoffError("auth_repair_resume repair result differs from validated receipt")
        repair_reasons = _validate_auth_repair_result(repair_result, None)
        if repair_reasons:
            raise HandoffError("; ".join(repair_reasons))
        if original_packet.get("run_id") != run_id:
            raise HandoffError("auth_repair_resume run_id differs from original packet")
        if original_packet.get("owner") != selected_owner:
            raise HandoffError("auth_repair_resume owner differs from original packet")
        if original_packet.get("modalities") != modalities:
            raise HandoffError("auth_repair_resume modalities differ from original packet")
        requested_outcome = original_packet.get("requested_outcome")
        constraints = original_packet.get("constraints")
        inputs = original_packet.get("inputs")
        effect_policy = original_packet.get("effect_policy")
        evidence_contract = original_packet.get("evidence_contract")
        idempotency_key = original_packet.get("idempotency_key")
        if not all(
            isinstance(value, dict) for value in (constraints, inputs, effect_policy)
        ):
            raise HandoffError("auth_repair_resume original packet objects are malformed")
        if not isinstance(evidence_contract, list) or not isinstance(idempotency_key, str):
            raise HandoffError("auth_repair_resume original packet contract is malformed")
        resume = {
            "kind": "auth_repair",
            "original_packet_sha256": original_packet_sha256,
            "repair_receipt_ref": repair_receipt_ref,
            "adapter_id": repair_result["adapter_id"],
            "classified_rung": repair_result["classified_rung"],
        }

    packet = {
        "schema": PACKET_SCHEMA,
        "run_id": run_id,
        "state": "explore_execute",
        "action": "execute_route",
        "owner": selected_owner,
        "requested_outcome": requested_outcome,
        "modalities": modalities,
        "constraints": constraints,
        "inputs": inputs,
        "capability_policy": capability_policy(selected_owner, modalities),
        "expected_events": {key: list(value) for key, value in EXPECTED_EVENTS.items()},
        "effect_policy": effect_policy,
        "evidence_contract": evidence_contract,
        "idempotency_key": idempotency_key,
    }
    if resume is not None:
        packet["resume"] = resume
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


def _validate_auth_repair_required(repair: Any) -> list[str]:
    if not isinstance(repair, dict):
        return ["auth_repair must be an object"]
    reasons: list[str] = []
    allowed = {
        "source",
        "status",
        "recoverable",
        "adapter_id",
        "env_var",
        "classified_rung",
        "distinguishing_error",
        "evidence_refs",
    }
    unknown = set(repair) - allowed
    if unknown:
        reasons.append(
            f"auth repair contains undeclared fields: {', '.join(sorted(unknown))}"
        )
    if repair.get("source") != "rote_auth_repair_required":
        reasons.append("auth repair source must be rote_auth_repair_required")
    if repair.get("status") != "required":
        reasons.append("auth repair status must be required")
    if repair.get("recoverable") is not True:
        reasons.append("auth repair must be explicitly recoverable")
    for field in (
        "adapter_id",
        "env_var",
        "classified_rung",
        "distinguishing_error",
    ):
        value = repair.get(field)
        if not isinstance(value, str) or not value:
            reasons.append(f"auth repair requires non-empty {field}")
    evidence_refs = repair.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) or not item for item in evidence_refs)
    ):
        reasons.append("auth repair requires non-empty evidence_refs")
    return reasons


def prepare_auth_repair_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a dedicated repair packet without widening the execution owner set."""

    run_id = _string(payload, "run_id")
    available_owners = _string_list(payload, "available_owners")
    if AUTH_REPAIR_OWNER not in available_owners:
        reason = f"required Rote specialist {AUTH_REPAIR_OWNER} is not callable in this harness"
        return {
            "schema": "play.auth-repair-handoff-preparation/v1",
            "ok": False,
            "event": "auth_repair_specialist_unavailable",
            "available": False,
            "reason": reason,
            "blocked_reason": reason,
            "required_owner": AUTH_REPAIR_OWNER,
            "available_owners": sorted(set(available_owners)),
        }

    auth_repair = _object(payload, "auth_repair")
    repair_reasons = _validate_auth_repair_required(auth_repair)
    if repair_reasons:
        raise HandoffError("; ".join(repair_reasons))
    original_packet = _object(payload, "original_packet")
    original_packet_sha256 = _string(payload, "original_packet_sha256")
    if original_packet.get("schema") != PACKET_SCHEMA:
        raise HandoffError(f"original_packet must use {PACKET_SCHEMA}")
    if stable_sha(original_packet) != original_packet_sha256:
        raise HandoffError("original_packet_sha256 does not match original_packet")
    if original_packet.get("run_id") != run_id:
        raise HandoffError("original_packet run_id does not match auth repair run")
    modalities = original_packet.get("modalities")
    if not isinstance(modalities, list) or "call" not in modalities:
        raise HandoffError("auth repair requires an original CALL packet")
    capability = original_packet.get("capability_policy")
    if not isinstance(capability, dict) or capability.get("kind") != "rote_adapter":
        raise HandoffError("auth repair requires original Rote adapter provenance")

    packet = {
        "schema": AUTH_REPAIR_PACKET_SCHEMA,
        "run_id": run_id,
        "state": "auth_repair_execute",
        "action": "execute_auth_repair",
        "owner": AUTH_REPAIR_OWNER,
        "requested_outcome": original_packet.get("requested_outcome"),
        "auth_repair": auth_repair,
        "original_packet": original_packet,
        "original_packet_sha256": original_packet_sha256,
        "expected_events": {
            key: list(value) for key, value in AUTH_REPAIR_EXPECTED_EVENTS.items()
        },
        "evidence_contract": _string_list(payload, "evidence_contract"),
        "idempotency_key": _string(payload, "idempotency_key"),
    }
    packet_sha256 = stable_sha(packet)
    return {
        "schema": "play.auth-repair-handoff-preparation/v1",
        "ok": True,
        "event": "auth_repair_handoff_ready",
        "available": True,
        "owner": AUTH_REPAIR_OWNER,
        "packet": packet,
        "packet_sha256": packet_sha256,
        "expected_events": sorted(AUTH_REPAIR_EXPECTED_EVENTS),
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


def _invalid_auth_repair_receipt(*reasons: str) -> dict[str, Any]:
    return {
        "schema": "play.auth-repair-handoff-verification/v1",
        "ok": False,
        "event": "auth_repair_receipt_invalid",
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
        elif event == "auth_repair_required":
            if not isinstance(modalities, list) or "call" not in modalities:
                reasons.append("auth repair required is valid only for a CALL route")
            unknown = set(result_payload) - {"auth_repair"}
            if unknown:
                reasons.append(
                    "auth repair receipt payload contains undeclared fields: "
                    + ", ".join(sorted(unknown))
                )
            reasons.extend(_validate_auth_repair_required(result_payload.get("auth_repair")))
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
            "auth_repair_required": "specialist_auth_repair_required",
        }[event],
        "owner": packet["owner"],
        "packet_sha256": packet_sha256,
        "receipt_ref": stable_sha(receipt),
        "receipt_valid": True,
        "evidence_refs": evidence_refs,
    }


def _validate_auth_repair_result(result: Any, requested: Any) -> list[str]:
    if not isinstance(result, dict):
        return ["receipt auth_repair must be an object"]
    reasons: list[str] = []
    allowed = {
        "source",
        "status",
        "adapter_id",
        "env_var",
        "classified_rung",
        "repair_action",
        "evidence_refs",
    }
    unknown = set(result) - allowed
    if unknown:
        reasons.append(
            f"auth repair result contains undeclared fields: {', '.join(sorted(unknown))}"
        )
    if result.get("source") != "rote_auth_repair_result":
        reasons.append("auth repair result source must be rote_auth_repair_result")
    if result.get("status") != "repaired":
        reasons.append("auth repair result status must be repaired")
    for field in ("adapter_id", "env_var", "classified_rung"):
        value = result.get(field)
        if not isinstance(value, str) or not value:
            reasons.append(f"auth repair result requires non-empty {field}")
        elif isinstance(requested, dict) and value != requested.get(field):
            reasons.append(f"auth repair result {field} does not match request")
    repair_action = result.get("repair_action")
    if not isinstance(repair_action, str) or not repair_action:
        reasons.append("auth repair result requires non-empty repair_action")
    evidence_refs = result.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) or not item for item in evidence_refs)
    ):
        reasons.append("auth repair result requires non-empty evidence_refs")
    return reasons


def verify_auth_repair_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a repair receipt against its exact repair packet."""

    packet = payload.get("packet")
    receipt = payload.get("receipt")
    if not isinstance(packet, dict) or not isinstance(receipt, dict):
        return _invalid_auth_repair_receipt("packet and receipt must be objects")
    if packet.get("schema") != AUTH_REPAIR_PACKET_SCHEMA:
        return _invalid_auth_repair_receipt(
            f"packet must use {AUTH_REPAIR_PACKET_SCHEMA}"
        )
    if receipt.get("schema") != AUTH_REPAIR_RECEIPT_SCHEMA:
        return _invalid_auth_repair_receipt(
            f"receipt must use {AUTH_REPAIR_RECEIPT_SCHEMA}"
        )

    reasons: list[str] = []
    packet_allowed = {
        "schema",
        "run_id",
        "state",
        "action",
        "owner",
        "requested_outcome",
        "auth_repair",
        "original_packet",
        "original_packet_sha256",
        "expected_events",
        "evidence_contract",
        "idempotency_key",
    }
    packet_unknown = set(packet) - packet_allowed
    if packet_unknown:
        reasons.append(
            "auth repair packet contains undeclared fields: "
            + ", ".join(sorted(packet_unknown))
        )
    receipt_allowed = {
        "schema",
        "packet_sha256",
        "run_id",
        "state",
        "action",
        "owner",
        "executor",
        "event",
        "payload",
        "evidence_refs",
    }
    receipt_unknown = set(receipt) - receipt_allowed
    if receipt_unknown:
        reasons.append(
            "auth repair receipt contains undeclared fields: "
            + ", ".join(sorted(receipt_unknown))
        )
    if packet.get("state") != "auth_repair_execute":
        reasons.append("auth repair packet state must be auth_repair_execute")
    if packet.get("action") != "execute_auth_repair":
        reasons.append("auth repair packet action must be execute_auth_repair")
    if packet.get("owner") != AUTH_REPAIR_OWNER:
        reasons.append(f"auth repair packet owner must be {AUTH_REPAIR_OWNER}")
    if packet.get("expected_events") != {
        key: list(value) for key, value in AUTH_REPAIR_EXPECTED_EVENTS.items()
    }:
        reasons.append("auth repair packet expected events differ from the closed contract")
    packet_sha256 = stable_sha(packet)
    if receipt.get("packet_sha256") != packet_sha256:
        reasons.append("auth repair receipt packet hash does not match")
    for field in ("run_id", "state", "action", "owner"):
        if receipt.get(field) != packet.get(field):
            reasons.append(f"auth repair receipt {field} does not match packet")
    executor = receipt.get("executor")
    if not isinstance(executor, dict):
        reasons.append("auth repair receipt executor is missing")
    else:
        if executor.get("kind") != "skill":
            reasons.append("auth repair receipt executor kind must be skill")
        if executor.get("name") != AUTH_REPAIR_OWNER:
            reasons.append("auth repair receipt executor must be rote-adapter-config")

    event = receipt.get("event")
    required_fields = AUTH_REPAIR_EXPECTED_EVENTS.get(event)
    if not isinstance(event, str) or required_fields is None:
        reasons.append("auth repair receipt event is not declared")
    result_payload = receipt.get("payload")
    if not isinstance(result_payload, dict):
        reasons.append("auth repair receipt payload must be an object")
    elif required_fields is not None:
        missing = [field for field in required_fields if field not in result_payload]
        if missing:
            reasons.append(f"auth repair receipt payload is missing: {', '.join(missing)}")
        unknown = set(result_payload) - set(required_fields)
        if unknown:
            reasons.append(
                "auth repair receipt payload contains undeclared fields: "
                + ", ".join(sorted(unknown))
            )
        if event == "auth_repair_ready":
            reasons.extend(
                _validate_auth_repair_result(
                    result_payload.get("auth_repair"), packet.get("auth_repair")
                )
            )
        elif event == "auth_repair_failed":
            reason = result_payload.get("reason")
            if not isinstance(reason, str) or not reason:
                reasons.append("auth repair failure requires a non-empty reason")
            failure_evidence = result_payload.get("evidence_refs")
            if (
                not isinstance(failure_evidence, list)
                or not failure_evidence
                or any(not isinstance(item, str) or not item for item in failure_evidence)
            ):
                reasons.append("auth repair failure requires non-empty evidence_refs")
    evidence_refs = receipt.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(item, str) or not item for item in evidence_refs)
    ):
        reasons.append("auth repair receipt evidence_refs must be a non-empty string list")
    if reasons:
        return _invalid_auth_repair_receipt(*reasons)

    return {
        **result_payload,
        "schema": "play.auth-repair-handoff-verification/v1",
        "ok": True,
        "event": (
            "specialist_auth_repair_ready"
            if event == "auth_repair_ready"
            else "specialist_auth_repair_failed"
        ),
        "owner": AUTH_REPAIR_OWNER,
        "packet_sha256": packet_sha256,
        "receipt_ref": stable_sha(receipt),
        "receipt_valid": True,
        "evidence_refs": evidence_refs,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="play-handoff", description=__doc__)
    parser.add_argument(
        "command",
        choices=("prepare", "verify", "prepare-auth-repair", "verify-auth-repair"),
    )
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
        handlers = {
            "prepare": prepare_handoff,
            "verify": verify_receipt,
            "prepare-auth-repair": prepare_auth_repair_handoff,
            "verify-auth-repair": verify_auth_repair_receipt,
        }
        result = handlers[args.command](payload)
    except (HandoffError, json.JSONDecodeError) as error:
        print(f"play-handoff: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
