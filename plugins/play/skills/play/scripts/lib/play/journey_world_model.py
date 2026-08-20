"""Capability lifecycle contract for Journey's spatial world model."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


CAPABILITY_INSTANCE_SCHEMA = "play.journey-capability-instance/v1"
MODALITY_BY_FAMILY = {
    "adapter": "call",
    "proc": "shell",
    "browser": "drive",
}
LIFECYCLE_PHASES = {"initialize", "authorize", "use", "observe", "close"}


def modality_for_capability(capability: Mapping[str, Any]) -> str | None:
    """Return Rote's user-facing modality for an equipped capability family."""

    return MODALITY_BY_FAMILY.get(str(capability.get("family") or ""))


def capability_subject(capability: Mapping[str, Any]) -> str | None:
    """Return a stable, non-secret identity within one capability family."""

    family = str(capability.get("family") or "")
    if family not in MODALITY_BY_FAMILY:
        return None
    if family == "browser":
        # Browser primitives operate through one leased page/session capability.
        # Primitive identity belongs to the operation, not to the station.
        return "page-session"
    if family == "proc" and isinstance(capability.get("lease_id"), str):
        return f"lease:{capability['lease_id']}"
    value = capability.get("id")
    return str(value) if isinstance(value, str) and value else family


def capability_reference(capability: Mapping[str, Any]) -> str | None:
    family = str(capability.get("family") or "")
    subject = capability_subject(capability)
    if family not in MODALITY_BY_FAMILY or subject is None:
        return None
    digest = hashlib.sha256(f"{family}:{subject}".encode()).hexdigest()[:20]
    return f"cap_{digest}"


def lifecycle_phase(
    command_type: str,
    operation: str,
    capability: Mapping[str, Any],
    effect_profile: Mapping[str, Any],
) -> str:
    """Classify where an operation sits in the capability lifecycle."""

    phase = str(capability.get("phase") or "")
    primitive = str(capability.get("primitive") or "")
    risk_tags = effect_profile.get("risk_tags")
    risk_tags = risk_tags if isinstance(risk_tags, list) else []
    if command_type in {"InitSession", "DepsCheck", "Inject"}:
        return "initialize"
    if phase in {"probe", "protocol", "initialize"}:
        return "initialize"
    if primitive == "lease" and operation == "initialize":
        return "initialize"
    if operation == "adapter.auth.ensure" or "interactive_auth" in risk_tags:
        return "authorize"
    if command_type in {
        "QueryRead",
        "QueryExtract",
        "Display",
        "StreamFollow",
        "ProcessBackgroundStatus",
        "ProcessBackgroundWait",
    }:
        return "observe"
    if command_type == "ProcessBackgroundStop":
        return "close"
    return "use"


def enrich_operation(activity: dict[str, Any]) -> None:
    """Attach modality, capability ownership, and lifecycle to one activity."""

    capability_value = activity.get("capability")
    capability = capability_value if isinstance(capability_value, Mapping) else {}
    effect_value = activity.get("effect_profile")
    effect_profile = effect_value if isinstance(effect_value, Mapping) else {}
    command_type = str(activity.get("command_type") or "Unknown")
    operation = str(activity.get("operation") or command_type)
    modality = modality_for_capability(capability)
    reference = capability_reference(capability)
    phase = lifecycle_phase(command_type, operation, capability, effect_profile)
    activity["modality"] = modality
    activity["capability_ref"] = reference
    activity["lifecycle_phase"] = phase
    activity["semantic_kind"] = str(activity.get("kind") or "phase")


def _initialization_basis(activities: Sequence[Mapping[str, Any]]) -> str:
    initializer = next(
        (activity for activity in activities if activity.get("lifecycle_phase") == "initialize"),
        None,
    )
    if initializer is None:
        return "observed_use"
    command_type = str(initializer.get("command_type") or "")
    capability = initializer.get("capability")
    capability = capability if isinstance(capability, Mapping) else {}
    if str(capability.get("phase") or "") == "probe":
        return "observed_probe"
    if command_type == "InitSession":
        return "observed_session_init"
    if command_type == "DepsCheck":
        return "observed_dependency_check"
    if command_type == "Inject":
        return "observed_input_init"
    return "observed_protocol_init"


def _authorization(activities: Sequence[Mapping[str, Any]], family: str) -> dict[str, Any]:
    authority = [
        activity
        for activity in activities
        if activity.get("lifecycle_phase") == "authorize"
    ]
    if authority:
        failed = authority[-1].get("status") == "failed"
        return {
            "state": "failed" if failed else "satisfied",
            "required": True,
            "basis": "typed_authority_operation",
        }
    if family == "proc":
        return {
            "state": "not_applicable",
            "required": False,
            "basis": "no_authority_signal",
        }
    return {
        "state": "unknown",
        "required": None,
        "basis": "not_observed",
    }


def capability_instances(activities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate operations into deterministic equipped capability instances."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for activity in activities:
        reference = activity.get("capability_ref")
        if isinstance(reference, str) and reference:
            grouped.setdefault(reference, []).append(activity)

    instances: list[dict[str, Any]] = []
    for reference, members in grouped.items():
        ordered = sorted(members, key=lambda item: int(item.get("sequence") or 0))
        first = ordered[0]
        capability_value = first.get("capability")
        capability = capability_value if isinstance(capability_value, Mapping) else {}
        family = str(capability.get("family") or "")
        modality = str(first.get("modality") or MODALITY_BY_FAMILY.get(family) or "")
        subject = capability_subject(capability) or family
        initialization_members = [
            item for item in ordered if item.get("lifecycle_phase") == "initialize"
        ]
        operation_sequences = [
            int(item["sequence"])
            for item in ordered
            if isinstance(item.get("sequence"), int)
            and item.get("lifecycle_phase") in {"use", "observe", "close"}
        ]
        final_phase = str(ordered[-1].get("lifecycle_phase") or "")
        failed = ordered[-1].get("status") == "failed"
        instances.append(
            {
                "schema": CAPABILITY_INSTANCE_SCHEMA,
                "id": reference,
                "modality": modality,
                "family": family,
                "interface": str(capability.get("interface") or "unknown"),
                "subject": subject,
                "label": str(capability.get("label") or subject),
                "state": (
                    "failed"
                    if failed
                    else "closed"
                    if final_phase == "close"
                    else "active"
                    if operation_sequences
                    else "ready"
                ),
                "initialization": {
                    "state": "initialized" if initialization_members else "ready",
                    "basis": _initialization_basis(ordered),
                    "first_sequence": int(first.get("sequence") or 0) or None,
                },
                "authorization": _authorization(ordered, family),
                "operation_sequences": operation_sequences,
                "evidence_sequences": [
                    int(item["sequence"])
                    for item in ordered
                    if isinstance(item.get("sequence"), int)
                ],
            }
        )
    return sorted(instances, key=lambda item: (int(item["initialization"]["first_sequence"] or 0), item["id"]))
