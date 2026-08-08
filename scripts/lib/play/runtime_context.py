"""Harness-owned logical context for the deterministic Play runtime."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator


class RuntimeContextError(RuntimeError):
    pass


SUPPORTED_MUTATION_SET_SHA256 = "fd53662267cc89e0d2332b037a5f0c8a66da5e143f2ef50b7f189a0f65843e8d"


def validate_mutation_contract(mutations: list[str]) -> None:
    canonical = "\n".join(sorted(mutations)).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != SUPPORTED_MUTATION_SET_SHA256:
        raise RuntimeContextError(
            "controller mutations changed without a reviewed runtime-context contract"
        )


def initial_context(
    *, run_id: str, task_key: str, machine_version: str, request_original: str
) -> dict[str, Any]:
    """Build the complete play.context/v1 record without inventing persistence."""

    return {
        "schema": "play.context/v1",
        "machine_version": machine_version,
        "run_id": run_id,
        "task_key": task_key,
        "state": "invoke",
        "transition_seq": 0,
        "mode": None,
        "request": {
            "original": request_original,
            "intent": None,
            "requested_outcome": None,
            "parameters": {},
            "excluded": False,
        },
        "search": {
            "complete": False,
            "query": None,
            "sources": [],
            "result_refs": [],
            "results": [],
            "play_choices": [],
        },
        "match": {
            "classification": None,
            "reference": None,
            "covered": [],
            "uncovered": [],
        },
        "inspection": {
            "complete": False,
            "exact_reference": None,
            "description": "",
            "local_change": None,
            "dependencies": {},
            "operations": [],
            "effects": {},
            "blockers": [],
            "disclosure_sha256": None,
        },
        "resolution": {
            "local_state": "unknown",
            "source": None,
            "pull_performed": False,
        },
        "play": {"version": None, "owner": None, "modalities": [], "effects": []},
        "readiness": {"status": "unknown", "exact_version": None},
        "route": {"modalities": [], "justification": None},
        "onboarding": {
            "intent": "unknown",
            "classify_ns": None,
            "rote_status": "unknown",
            "rote_command": None,
            "rote_off_path": False,
            "probe_ns": None,
            "identity_status": "unknown",
            "email": None,
            "email_handle": None,
            "identity_ref": None,
            "whoami_ns": None,
            "experience_status": "unknown",
            "experience_ref": None,
            "experience_ns": None,
            "orientation_version": None,
            "orientation_status": "pending",
            "orientation_markdown": None,
            "orientation_ref": None,
            "orientation_ns": None,
            "marker_ns": None,
            "starter_reference": None,
            "starter_status": "not_selected",
            "activation_status": "pending",
            "activation_markdown": None,
            "activation_ref": None,
            "activation_ns": None,
            "play_uri": None,
            "setup_status": "not_required",
            "card": None,
            "card_presented": False,
            "card_presentation_ref": None,
            "evidence_refs": [],
        },
        "exploration": {
            "welcome_status": "pending",
            "human_name": None,
            "identity_status": "unknown",
            "identity_source": "unknown",
            "identity_ref": None,
            "welcome_markdown": None,
            "welcome_ref": None,
            "resolve_ns": None,
        },
        "adapter_discovery": {
            "status": "unknown",
            "query": None,
            "searched_sources": [],
            "choices": [],
            "selected_id": None,
            "evidence_refs": [],
        },
        "consent": {"explore": "not_asked", "save": "not_asked"},
        "modality_policy": {
            "mode": "auto",
            "allowed": ["call", "shell", "drive"],
            "forbidden": [],
            "widening_requires_approval": True,
        },
        "judge_policy": {"allowed": False, "harness": None},
        "effect_policy": {
            "read_only": False,
            "approval_gates": [],
            "rote_confirmation": None,
        },
        "output_policy": {
            "mode": "detailed",
            "preferred_presentation": "human",
            "max_inline_bytes": 200_000,
            "overflow": "artifact",
        },
        "output": {
            "mode": None,
            "detail": None,
            "source": None,
            "format": None,
            "primary": None,
            "manifest": {"response_refs": [], "artifact_refs": [], "effects": []},
            "truncated": False,
            "full_output_ref": None,
            "presentation_markdown": None,
            "presentation_sha256": None,
            "inline_bytes": None,
            "primary_bytes": None,
            "format_ns": None,
        },
        "execution": {
            "owner": None,
            "workspace": None,
            "attempts": 0,
            "budget": 3,
            "pending_action": None,
            "idempotency_key": None,
        },
        "handoff": {
            "owner": None,
            "available": False,
            "packet": None,
            "packet_sha256": None,
            "expected_events": [],
            "receipt": None,
            "receipt_ref": None,
            "receipt_valid": False,
            "blocked_reason": None,
        },
        "auth_repair": {
            "status": "none",
            "owner": None,
            "recoverable": None,
            "adapter_id": None,
            "env_var": None,
            "classified_rung": None,
            "distinguishing_error": None,
            "repair_action": None,
            "original_packet": None,
            "original_packet_sha256": None,
            "packet": None,
            "packet_sha256": None,
            "receipt": None,
            "receipt_ref": None,
            "receipt_valid": False,
            "blocked_reason": None,
            "evidence_refs": [],
        },
        "evidence": {
            "baseline": None,
            "responses": [],
            "artifacts": [],
            "verification": None,
            "failed_receipt": None,
        },
        "candidate": {
            "reference": None,
            "reusable": None,
            "contract": None,
            "released_flow": None,
            "publication_status": "unknown",
        },
        "birth": {
            "selector": None,
            "sha256": None,
            "flow_fingerprint": None,
            "object_ref": None,
            "capture_ref": None,
            "exact_reference": None,
            "registry_content_hash": None,
            "binding_ref": None,
            "certificate_presented": False,
            "certificate_ref": None,
            "certificate_ns": None,
            "trace_learning": {
                "commands": 0,
                "responses": 0,
                "successes": 0,
                "errors": 0,
                "unknown": 0,
                "dependency_edges": 0,
                "modalities": [],
                "duration_seconds": None,
                "trace_method": "not_presented",
                "summary": "Birth certificate presentation is pending.",
            },
        },
        "awareness": {
            "window_days": 7,
            "complete": False,
            "digest_ref": None,
            "play_choices": [],
        },
        "creator": {"intent": None, "seed_reference": None},
        "management": {
            "views": ["org_summary", "plays_by_org"],
            "org_summary_ref": None,
            "plays_by_org_ref": None,
        },
        "publication": {
            "owner": None,
            "owner_resolution": "unknown",
            "profile_handle": None,
            "owner_choices": [],
            "owner_summary": None,
            "owner_probe_ref": None,
            "owner_probe_ns": None,
            "private_org": None,
            "canonical_reference": None,
            "birth_sha256": None,
            "title": None,
            "description": None,
            "uri": None,
            "install_uri": None,
            "content_hash": None,
            "visibility": None,
            "indexed": False,
            "index_ref": None,
            "inspect_ref": None,
            "share_copy": {"x": None, "linkedin": None},
            "presentation_ref": None,
            "presented": False,
        },
        "publication_validation": {
            "credential_status": "not_required",
            "adapter_contracts": [],
            "credential_contract_sha256": None,
            "credential_check_ns": None,
            "smoke_status": "not_required",
            "smoke_exact_reference": None,
            "smoke_run_ref": None,
            "smoke_output_sha256": None,
            "smoke_output_bytes": None,
            "smoke_ns": None,
            "isolated_workdir": False,
            "failure_reason": None,
            "evidence_refs": [],
        },
        "receipt_ref": None,
        "last_event": {"id": None, "payload_ref": None},
    }


def apply_event(
    context: Mapping[str, Any],
    *,
    event_id: str,
    payload: Mapping[str, Any],
    state: str,
    transition_seq: int,
    mutation: str,
) -> dict[str, Any]:
    """Merge typed event fields into known context roots and advance the cursor mirror."""

    updated = copy.deepcopy(dict(context))
    expanded = _expand_dotted(payload)
    _merge_known(updated, expanded)
    _merge_event_aliases(updated, expanded)
    _apply_mutation_semantics(updated, mutation, expanded)
    updated["state"] = state
    updated["transition_seq"] = transition_seq
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    updated["last_event"] = {
        "id": event_id,
        "payload_ref": "sha256:" + hashlib.sha256(payload_json.encode()).hexdigest(),
    }
    return updated


_CONSTANT_PATCHES: dict[str, dict[str, Any]] = {
    "start_greeting_onboarding": {"onboarding.intent": "greeting"},
    "start_uri_onboarding": {"onboarding.intent": "play_uri"},
    "enter_onboarding_uri_use": {"mode": "use"},
    "enter_onboarding_starter_use": {
        "mode": "use",
        "onboarding.starter_status": "selected",
    },
    "enter_onboarding_goal": {"mode": "explore"},
    "enter_onboarding_awareness": {"mode": "awareness"},
    "set_request_contract": {"mode": "use"},
    "set_search_request": {"mode": "awareness"},
    "set_awareness_request": {"mode": "awareness"},
    "set_creator_request": {"mode": "create"},
    "enter_awareness_use": {"mode": "use"},
    "set_awareness_search": {"mode": "awareness"},
    "approve_creator_explore": {"mode": "explore", "consent.explore": "approved"},
    "approve_adapt_explore": {"mode": "explore", "consent.explore": "approved"},
    "enter_creator_use": {"mode": "use"},
    "record_non_outcome_exit": {"mode": "exited"},
    "record_explicit_exit": {"mode": "exited", "request.excluded": True},
    "set_management_request": {"mode": "manage"},
    "set_birth_request": {"mode": "manage"},
    "enter_search_use": {"mode": "use"},
    "enter_use": {"mode": "use", "match.classification": "full"},
    "downgrade_inadequate_match": {"match.classification": "partial"},
    "record_partial_match": {"match.classification": "partial"},
    "record_uncertain_match": {"match.classification": "uncertain"},
    "record_no_match": {"match.classification": "none"},
    "enter_direct_use": {"mode": "use"},
    "attach_onboarding_starter_receipt": {"onboarding.starter_status": "completed"},
    "approve_repair_explore": {"mode": "explore", "consent.explore": "approved"},
    "record_use_auth_repair_required": {"auth_repair.status": "required"},
    "record_ordinary_exit": {"mode": "exited"},
    "approve_explore": {"mode": "explore", "consent.explore": "approved"},
    "record_missing_consent": {"consent.explore": "declined"},
    "select_adapter_source": {"adapter_discovery.status": "selected"},
    "record_catalog_rejection": {"adapter_discovery.status": "catalog_rejected"},
    "approve_effect_confirmation": {"effect_policy.rote_confirmation.status": "approved"},
    "decline_effect_confirmation": {"effect_policy.rote_confirmation.status": "declined"},
    "record_auth_repair_required": {"auth_repair.status": "required"},
    "approve_auth_repair": {"auth_repair.status": "approved"},
    "decline_auth_repair": {"auth_repair.status": "declined"},
    "record_auth_repair_handoff": {"auth_repair.status": "repairing"},
    "record_auth_repair_success": {"auth_repair.status": "repaired"},
    "record_auth_repair_failure": {"auth_repair.status": "failed"},
    "record_unpublished_result": {"candidate.publication_status": "unknown"},
    "choose_private": {"consent.save": "private"},
    "choose_public": {"consent.save": "public"},
    "choose_resolved_public_owner": {"consent.save": "public"},
    "record_save_skipped": {"consent.save": "skip"},
    "record_publication_boundary_violation": {"candidate.publication_status": "published"},
    "record_index": {"publication.indexed": True},
    "record_birth_certificate_presentation": {
        "birth.certificate_presented": True,
        "publication.presented": True,
    },
}


def _apply_mutation_semantics(
    context: dict[str, Any], mutation: str, payload: Mapping[str, Any]
) -> None:
    for path, value in _CONSTANT_PATCHES.get(mutation, {}).items():
        _set_existing_path(context, path, value)

    if mutation == "enter_use":
        # Search result descriptions and choices are presentation data. Once a match is
        # selected they must not inflate every subsequent private continuation.
        selected = _path_value(payload, "match.reference")
        context["search"]["results"] = []
        context["search"]["play_choices"] = []
        context["search"]["result_refs"] = [selected] if isinstance(selected, str) else []

    if mutation == "record_unrunnable_inspection":
        selected = context["match"].get("reference")
        context["search"]["results"] = [
            result
            for result in context["search"]["results"]
            if not isinstance(result, Mapping) or result.get("reference") != selected
        ]
        context["search"]["play_choices"] = [
            choice
            for choice in context["search"]["play_choices"]
            if not isinstance(choice, Mapping) or choice.get("reference") != selected
        ]
        context["search"]["result_refs"] = [
            reference
            for reference in context["search"]["result_refs"]
            if reference != selected
        ]

    if mutation == "approve_inspected_run":
        context["search"]["results"] = []
        context["search"]["play_choices"] = []

    if mutation == "enter_onboarding_starter_use":
        starter = _path_value(payload, "onboarding.starter_reference")
        if isinstance(starter, str) and starter:
            context["match"]["reference"] = starter
            _bind_direct_play_request(context, starter)
    elif mutation == "start_uri_onboarding":
        play_uri = _path_value(payload, "onboarding.play_uri")
        if isinstance(play_uri, str) and play_uri:
            context["match"]["reference"] = play_uri
    elif mutation == "enter_onboarding_uri_use":
        reference = context["match"].get("reference")
        if isinstance(reference, str) and reference:
            _bind_direct_play_request(context, reference)
    elif mutation == "approve_adapt_explore":
        reference = _path_value(payload, "match.reference")
        if isinstance(reference, str) and reference:
            context["creator"]["seed_reference"] = reference
    elif mutation == "record_verification":
        refs = payload.get("evidence_refs")
        if isinstance(refs, list) and refs:
            context["evidence"]["verification"] = refs[0]
    elif mutation == "record_failed_receipt":
        refs = payload.get("evidence_refs")
        if isinstance(refs, list) and refs:
            context["evidence"]["failed_receipt"] = refs[0]
    elif mutation == "record_effect_confirmation":
        confirmation = payload.get("effect_policy")
        if isinstance(confirmation, Mapping):
            rote_confirmation = confirmation.get("rote_confirmation")
            if isinstance(rote_confirmation, Mapping):
                context["effect_policy"]["rote_confirmation"] = copy.deepcopy(
                    dict(rote_confirmation)
                )
    elif mutation == "widen_modality_policy":
        allowed = payload.get("allowed")
        if isinstance(allowed, list):
            context["modality_policy"]["allowed"] = allowed
    elif mutation == "consume_attempt":
        context["execution"]["attempts"] += 1


def _bind_direct_play_request(context: dict[str, Any], reference: str) -> None:
    """Complete the request contract for a lexically exact Play selection."""

    context["request"]["intent"] = f"run {reference}"
    context["request"]["requested_outcome"] = (
        f"Run {reference} and return its complete output."
    )
    context["request"]["parameters"] = {}


def _set_existing_path(context: dict[str, Any], path: str, value: Any) -> None:
    current: Any = context
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise RuntimeContextError(f"mutation patch targets unknown context path {path}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise RuntimeContextError(f"mutation patch targets unknown context path {path}")
    current[parts[-1]] = copy.deepcopy(value)


def validate_context(context: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(context), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(map(str, first.path)) or "context"
        raise RuntimeContextError(f"invalid play.context/v1 at {location}: {first.message}")


def validate_required(context: Mapping[str, Any], required: tuple[str, ...]) -> None:
    missing = [path for path in required if not _has_path(context, path)]
    if missing:
        raise RuntimeContextError(
            "target state context is missing required fields: " + ", ".join(missing)
        )


def _expand_dotted(payload: Mapping[str, Any]) -> dict[str, Any]:
    expanded: dict[str, Any] = {}
    for key, value in payload.items():
        if "." not in key:
            if isinstance(value, Mapping):
                expanded[key] = _expand_dotted(value)
            else:
                expanded[key] = copy.deepcopy(value)
            continue
        current = expanded
        parts = key.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = copy.deepcopy(value)
    return expanded


def _merge_known(target: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key in target.keys() & patch.keys():
        value = patch[key]
        if isinstance(target[key], dict) and isinstance(value, Mapping):
            if target[key]:
                _merge_known(target[key], value)
            else:
                target[key] = copy.deepcopy(dict(value))
        else:
            target[key] = copy.deepcopy(value)


def _merge_event_aliases(context: dict[str, Any], payload: Mapping[str, Any]) -> None:
    evidence_refs = payload.get("evidence_refs")
    if isinstance(evidence_refs, list):
        context["evidence"]["responses"] = list(dict.fromkeys(evidence_refs))
    response_refs = payload.get("response_refs")
    if isinstance(response_refs, list):
        context["output"]["manifest"]["response_refs"] = response_refs
        context["evidence"]["responses"] = response_refs
    artifact_refs = payload.get("artifact_refs")
    if isinstance(artifact_refs, list):
        context["output"]["manifest"]["artifact_refs"] = artifact_refs
        context["evidence"]["artifacts"] = artifact_refs
    effects = payload.get("effects")
    if isinstance(effects, list):
        context["output"]["manifest"]["effects"] = effects
    owner = payload.get("owner")
    if isinstance(owner, str) and owner:
        context["publication"]["owner"] = owner
    visibility = payload.get("visibility")
    if visibility in {"private", "public"}:
        context["publication"]["visibility"] = visibility


def _has_path(payload: Mapping[str, Any], path: str) -> bool:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return current is not None


def _path_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current
