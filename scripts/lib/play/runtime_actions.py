"""Deterministic action execution for Play's advance-until-yield loop."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .controller import (
    ControllerEvent,
    ControllerRuntime,
    ControllerRuntimeError,
    EventId,
    RuntimeSession,
)
from .inspection import render_markdown as render_inspection_markdown
from .digest import render_markdown as render_digest_markdown
from .executors import RUNTIME_COMMANDLESS_ACTIONS
from .search import render_markdown as render_search_markdown
from .state_home import state_path


_PLACEHOLDER = re.compile(r"<([a-z][a-z0-9_.-]*)>")
_SELECTOR_ACTIONS = {
    "classify_play_invocation",
    "probe_rote_for_onboarding",
    "inspect_onboarding_identity",
    "inspect_onboarding_experience",
    "login_rote_identity",
    "inspect_registry_play",
    "collect_awareness_digest",
    "resolve_public_owner",
    "inspect_publication_credentials",
    "classify_adequacy",
    "present_search_results",
    "run_registry_play",
    "verify_play_output",
}

_DEFAULT_ACTION_TIMEOUT_SECONDS = 120
_MAX_ACTION_TIMEOUT_SECONDS = 3600
@dataclass(frozen=True)
class DeterministicTrace:
    state: str
    action: str
    event: str
    elapsed_ns: int


@dataclass(frozen=True)
class RuntimeYield:
    schema: str
    session: RuntimeSession
    projection: Mapping[str, Any]
    trace: tuple[DeterministicTrace, ...]
    presentations: tuple[Any, ...]


def advance_until_yield(
    runtime: ControllerRuntime,
    session: RuntimeSession,
    *,
    root: Path,
    max_actions: int = 32,
    transition_observer: Callable[..., None] | None = None,
) -> RuntimeYield:
    """Execute eligible deterministic Play actions until human/model work is required."""

    trace: list[DeterministicTrace] = []
    presentations: list[Any] = []
    current = session
    for _ in range(max_actions):
        projection = runtime.project_session(current).as_dict()
        instruction = projection.get("instruction")
        if not _is_executable(instruction, projection):
            return RuntimeYield(
                schema="play.runtime-yield/v1",
                session=current,
                projection=projection,
                trace=tuple(trace),
                presentations=tuple(presentations),
            )
        assert isinstance(instruction, Mapping)
        started = time.perf_counter_ns()
        event, presentation = _execute_instruction(
            instruction,
            projection=projection,
            context=current.context,
            root=root,
        )
        result = runtime.advance_session(current, event)
        if transition_observer is not None:
            transition_observer(
                source=str(current.cursor.state),
                event=str(event.id),
                target=str(result.session.cursor.state),
                context=result.session.context,
            )
        trace.append(
            DeterministicTrace(
                state=str(current.cursor.state),
                action=str(instruction["id"]),
                event=str(event.id),
                elapsed_ns=time.perf_counter_ns() - started,
            )
        )
        if presentation is not None:
            presentations.append(presentation)
        current = result.session
    projection = runtime.project_session(current).as_dict()
    if not _is_executable(projection.get("instruction"), projection):
        return RuntimeYield(
            schema="play.runtime-yield/v1",
            session=current,
            projection=projection,
            trace=tuple(trace),
            presentations=tuple(presentations),
        )
    raise ControllerRuntimeError(
        f"deterministic action limit {max_actions} reached without a yield boundary"
    )


def _is_executable(
    instruction: object, projection: Mapping[str, Any]
) -> bool:
    if not isinstance(instruction, Mapping):
        return False
    if instruction.get("type") != "action" or instruction.get("executor") != "runtime":
        return False
    command = instruction.get("command")
    if command is None and instruction.get("id") not in RUNTIME_COMMANDLESS_ACTIONS:
        return False
    if command is not None and (
        not isinstance(command, str) or not command.startswith("scripts/bin/")
    ):
        return False
    success_events = [
        event
        for event in projection.get("accepted_events", {})
        if event != "action_blocked"
    ]
    return len(success_events) == 1 or instruction.get("id") in _SELECTOR_ACTIONS


def _execute_instruction(
    instruction: Mapping[str, Any],
    *,
    projection: Mapping[str, Any],
    context: Mapping[str, Any],
    root: Path,
) -> tuple[ControllerEvent, Any | None]:
    command = instruction.get("command")
    recoverable_event: str | None = None
    if command is None:
        raw = _commandless_result(str(instruction["id"]), context)
    else:
        argv = _render_command(str(command), context, root)
        environment = os.environ.copy()
        environment.setdefault("ROTE_FLOW_PROGRESS", "0")
        environment.setdefault("ROTE_NO_HINTS", "1")
        try:
            timeout_seconds = instruction.get(
                "timeout_seconds", _DEFAULT_ACTION_TIMEOUT_SECONDS
            )
            if (
                not isinstance(timeout_seconds, int)
                or isinstance(timeout_seconds, bool)
                or not 1 <= timeout_seconds <= _MAX_ACTION_TIMEOUT_SECONDS
            ):
                raise ControllerRuntimeError(
                    f"{instruction['id']} declares an invalid timeout_seconds"
                )
            completed = subprocess.run(
                argv,
                cwd=root,
                env=environment,
                input=(
                    json.dumps(instruction.get("input", {}))
                    if "--stdin" in argv
                    else None
                ),
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            reason = str(error)
            return _blocked_action_event(instruction, reason), reason
        if completed.returncode != 0:
            raw = {}
            if completed.stdout.strip():
                try:
                    raw = _parse_action_output(instruction, completed.stdout)
                except ControllerRuntimeError:
                    raw = {}
            recoverable_event = _failure_result_event(str(instruction["id"]), raw)
        else:
            raw = _parse_action_output(instruction, completed.stdout)
        if completed.returncode != 0 and recoverable_event is None:
            reason = (completed.stderr or completed.stdout).strip()
            reason = reason or f"{instruction['id']} failed"
            return _blocked_action_event(instruction, reason), reason

    event_id = recoverable_event or _select_event(str(instruction["id"]), raw, projection)
    raw = _derive_result_fields(event_id, raw)
    required = projection["accepted_events"][event_id]["required_payload"]
    payload = _build_payload(required, raw, context)
    presentation = _presentation(raw)
    if event_id == "action_blocked" and presentation is None:
        reason = payload.get("reason")
        if isinstance(reason, str) and reason.strip():
            presentation = reason.strip()
    if event_id == "authentication_receipt_invalid" and presentation is None:
        authentication = payload.get("authentication")
        if isinstance(authentication, Mapping):
            reason = authentication.get("blocked_reason")
            if isinstance(reason, str) and reason.strip():
                presentation = reason.strip()
    if (
        instruction.get("id") == "inspect_registry_play"
        and event_id in {"play_inspected", "play_not_runnable"}
    ):
        presentation = render_inspection_markdown(raw)
    return ControllerEvent(id=EventId(event_id), payload=payload, guards={}), presentation


def _blocked_action_event(
    instruction: Mapping[str, Any], reason: str
) -> ControllerEvent:
    return ControllerEvent(
        id=EventId("action_blocked"),
        payload={
            "reason": reason,
            "recoverable": False,
            "owner": str(instruction.get("owner", "play")),
            "evidence_refs": [],
        },
        guards={},
    )


def _commandless_result(
    action_id: str, context: Mapping[str, Any]
) -> dict[str, Any]:
    if action_id == "present_report_card":
        inspection = context.get("inspection")
        card = inspection.get("audit_card") if isinstance(inspection, Mapping) else None
        reference = inspection.get("exact_reference") if isinstance(inspection, Mapping) else None
        markdown = (
            f"## Report card\n\n```text\n{card}\n```"
            if isinstance(card, str) and card.strip()
            else f"No report card was recorded for `{reference}`; the audit was unavailable at inspection. "
                 f"Run `play audit {str(reference).rsplit('@', 1)[0]}` for a fresh look."
        )
        return {"presentation": {"markdown": markdown}, "presentation_markdown": markdown}
    if action_id == "present_exploration_transition":
        state = context.get("state")
        outcome = _path_value(context, "request.requested_outcome")
        if not isinstance(state, str) or not isinstance(outcome, str) or not outcome:
            raise ControllerRuntimeError("exploration transition context is incomplete")
        goal_status = _path_value(context, "exploration.goal_status")
        provider = _path_value(context, "exploration.provider")
        provider_label = provider if isinstance(provider, str) and provider else "The selected tool"
        prerequisite_markdown = (
            "🔌 **Connection ready**\n\n"
            f"{provider_label} is connected and checked. Connection is setup, not the useful "
            "result. Tell Play what you want to accomplish with it next."
            if goal_status == "required"
            else (
                "🔌 **Prerequisite ready**\n\n"
                f"The selected route is prepared for **{outcome}**. Connection or setup is "
                "not the requested result; exploration is continuing in the same captured workspace."
            )
        )
        phase = {
            "exploration_begin": (
                "exploration_started",
                "🧭 **Exploration started**\n\n"
                f"**Outcome:** {outcome}\n\n"
                "Finding viable tools and routes now. You will choose before anything is "
                "adapted, installed, authenticated, or run.",
            ),
            "exploration_prerequisite_present": (
                "exploration_prerequisite_presented",
                prerequisite_markdown,
            ),
            "exploration_complete_present": (
                "exploration_completion_presented",
                "✓ **Exploration verified**\n\n"
                f"The requested outcome—**{outcome}**—was produced and checked. Play is now "
                "evaluating only the outcome-bearing steps for reuse; setup and connection probes are excluded.",
            ),
            "exploration_one_off_present": (
                "exploration_one_off_presented",
                "🧾 **Exploration complete**\n\n"
                f"**{outcome}** was useful for this run, but the verified trajectory did not "
                "meet the reusable-Play threshold. Nothing was saved or published.",
            ),
        }.get(state)
        if phase is None:
            raise ControllerRuntimeError(
                f"unsupported exploration presentation state {state}"
            )
        event, markdown = phase
        return {
            "event": event,
            "presentation": {"markdown": markdown},
            "presentation_markdown": markdown,
        }
    if action_id == "present_search_results":
        request = context.get("request")
        search = context.get("search")
        if not isinstance(request, Mapping) or not isinstance(search, Mapping):
            raise ControllerRuntimeError("search presentation context is malformed")
        original = request.get("intent") or request.get("original")
        normalized = search.get("query")
        results = search.get("results")
        if not isinstance(original, str) or not isinstance(normalized, str) or not isinstance(results, list):
            raise ControllerRuntimeError("search presentation context is incomplete")
        return {
            "event": "search_empty" if not results else "search_presented",
            "presentation_markdown": render_search_markdown(
                original, normalized, results
            )
        }
    if action_id == "present_awareness_digest":
        return {}
    if action_id == "present_play_management":
        management = context.get("management")
        if not isinstance(management, Mapping):
            raise ControllerRuntimeError("management presentation context is malformed")
        return {"management": dict(management)}
    if action_id == "build_receipt":
        primary = _path_value(context, "output.primary")
        output_format = _path_value(context, "output.format")
        output_source = _path_value(context, "output.source")
        if primary is None or not isinstance(output_format, str) or not output_format:
            raise ControllerRuntimeError("receipt output is incomplete")
        if not isinstance(output_source, str) or not output_source:
            raise ControllerRuntimeError("receipt output source is incomplete")
        if isinstance(primary, str):
            primary_bytes_value = primary.encode("utf-8")
        else:
            try:
                primary_bytes_value = json.dumps(
                    primary, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            except (TypeError, ValueError) as error:
                raise ControllerRuntimeError(
                    "receipt primary output is not JSON-serializable"
                ) from error
        primary_sha256 = hashlib.sha256(primary_bytes_value).hexdigest()
        receipt_source = {
            "reference": _path_value(context, "match.reference"),
            "verification": _path_value(context, "evidence.verification"),
            "primary_sha256": primary_sha256,
            "format": output_format,
            "source": output_source,
        }
        if not all(
            isinstance(value, str) and value for value in receipt_source.values()
        ):
            raise ControllerRuntimeError("receipt context is incomplete")
        canonical = json.dumps(receipt_source, sort_keys=True, separators=(",", ":"))
        return {
            "receipt_ref": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
            "output": {
                "presentation_sha256": primary_sha256,
                "primary_bytes": len(primary_bytes_value),
            },
            "presentation": primary,
        }
    if action_id == "replay_onboarding_result":
        primary = _path_value(context, "output.primary")
        if primary is None or primary == "":
            raise ControllerRuntimeError("onboarding result is unavailable for replay")
        return {
            "event": "onboarding_result_replayed",
            "presentation": primary,
        }
    if action_id == "classify_adequacy":
        search = context.get("search")
        request = context.get("request")
        if not isinstance(search, Mapping) or not isinstance(request, Mapping):
            raise ControllerRuntimeError("adequacy context is malformed")
        results = search.get("results")
        if not isinstance(results, list):
            raise ControllerRuntimeError("adequacy results are malformed")
        outcome = request.get("requested_outcome") or request.get("intent") or "requested outcome"
        capture = _capture_classification(context, str(outcome))
        if not results:
            return {
                "event": "no_match",
                "match": {"covered": [], "uncovered": [str(outcome)]},
                "confidence": 1.0,
                "capture": capture,
            }
        candidate = results[0]
        if not isinstance(candidate, Mapping):
            raise ControllerRuntimeError("adequacy candidate is malformed")
        classification = candidate.get("match_classification")
        reference = candidate.get("reference")
        if classification not in {"full", "partial", "uncertain"} or not isinstance(reference, str):
            raise ControllerRuntimeError("adequacy candidate is incomplete")
        event = {
            "full": "full_match",
            "partial": "partial_match",
            "uncertain": "uncertain_match",
        }[classification]
        covered = [str(candidate.get("name") or reference)]
        # Search reports the outcome tokens the card could not account for. A
        # "full" label with a non-empty remainder fails the
        # match_satisfies_constraints guard and is downgraded instead of run.
        remainder = candidate.get("uncovered_terms")
        uncovered = (
            [str(term) for term in remainder]
            if classification == "full" and isinstance(remainder, list)
            else []
            if classification == "full"
            else [str(outcome)]
        )
        match: dict[str, Any] = {
            "covered": covered,
            "uncovered": uncovered,
        }
        match["reference"] = reference
        result = {
            "event": event,
            "match": match,
            "confidence": float(candidate.get("coverage", 0.0)),
        }
        if event in {"partial_match", "uncertain_match"}:
            result["capture"] = capture
        return result
    if action_id == "verify_play_output":
        output = context.get("output")
        if not isinstance(output, Mapping):
            raise ControllerRuntimeError("Play output context is malformed")
        primary = output.get("primary")
        full_output_digest = _verified_full_output_digest(output)
        failed_postconditions = _output_envelope_failures(output, full_output_digest)
        complete = not failed_postconditions
        try:
            encoded = (
                full_output_digest.encode()
                if full_output_digest is not None
                else (
                    primary.encode()
                    if isinstance(primary, str)
                    else json.dumps(
                        primary, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    ).encode()
                )
            )
        except (TypeError, ValueError) as error:
            raise ControllerRuntimeError("Play output is not serializable") from error
        evidence_ref = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if complete:
            return {
                "event": "outcome_verified",
                "postconditions": ["complete Play output returned"],
                "evidence_refs": [evidence_ref],
            }
        return {
            "event": "outcome_not_verified",
            "failed_postconditions": failed_postconditions,
            "evidence_refs": [evidence_ref],
        }
    raise ControllerRuntimeError(f"no deterministic renderer for {action_id}")


def _output_envelope_failures(
    output: Mapping[str, Any], full_output_digest: str | None
) -> list[str]:
    """Name every field that keeps the result envelope from verifying.

    The specialist that reports an exploration outcome fills these fields by hand,
    so a rejection must say which field, what it held, and what verifies. A
    bare "incomplete or truncated" sent one consumer through two clean Rote
    workspaces hunting a trajectory fault that never existed.
    """

    failures: list[str] = []
    mode = output.get("mode")
    if mode != "detailed":
        failures.append(f"output.mode is {mode!r}; report \"detailed\"")
    detail = output.get("detail")
    if detail != "full":
        failures.append(
            f"output.detail is {detail!r}; report \"full\" when output.primary is the "
            "complete user-visible result, even when that result is itself a summary"
        )
    primary = output.get("primary")
    if primary is None or primary == "":
        failures.append("output.primary is empty; return the complete result inline")
    truncated = output.get("truncated")
    reference = output.get("full_output_ref")
    if truncated is True:
        if not isinstance(reference, str) or not reference:
            failures.append(
                "output.truncated is true without output.full_output_ref; return the "
                "complete result inline with output.truncated false"
            )
        elif full_output_digest is None:
            failures.append(
                f"output.full_output_ref {reference!r} is not an owner-private Play "
                "run-output artifact; return the complete result inline with "
                "output.truncated false and output.full_output_ref null"
            )
    elif truncated is not False:
        failures.append(f"output.truncated is {truncated!r}; report false")
    return failures


def _capture_classification(
    context: Mapping[str, Any], outcome: str
) -> dict[str, Any]:
    existing = context.get("capture")
    if isinstance(existing, Mapping) and existing.get("decision") in {"capture", "normal"}:
        return {
            "decision": existing.get("decision"),
            "reason": existing.get("reason"),
            "task_class": existing.get("task_class"),
        }
    normalized = outcome.casefold()
    capture_markers = (
        "implement",
        "build",
        "deploy",
        "release",
        "migrate",
        "automate",
        "audit",
        "report",
        "workflow",
        "fix all",
        "update docs",
        "test",
    )
    capture = len(outcome) >= 100 or sum(marker in normalized for marker in capture_markers) >= 2
    return {
        "decision": "capture" if capture else "normal",
        "reason": (
            "multi-step reusable outcome should be proxied through Rote"
            if capture
            else "bounded outcome does not justify a reusable trajectory"
        ),
        "task_class": "unclassified",
    }


def _verified_full_output_digest(output: Mapping[str, Any]) -> str | None:
    if output.get("truncated") is not True:
        return None
    reference = output.get("full_output_ref")
    if not isinstance(reference, str) or not reference.startswith("file:"):
        return None
    path = Path(reference.removeprefix("file:")).resolve()
    root = state_path("run-output").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_action_output(
    instruction: Mapping[str, Any], stdout: str
) -> dict[str, Any]:
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ControllerRuntimeError(
            f"deterministic action {instruction['id']} returned invalid JSON: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise ControllerRuntimeError(
            f"deterministic action {instruction['id']} returned a non-object"
        )
    return raw


def _failure_result_event(action_id: str, raw: Mapping[str, Any]) -> str | None:
    if action_id == "inspect_registry_play":
        error = raw.get("error")
        if isinstance(error, Mapping) and error.get("kind") == "play_not_found":
            return "play_reference_unresolved"
    return None


def _derive_result_fields(event_id: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    derived = dict(raw)
    if event_id == "empty_play_invocation":
        derived["onboarding"] = {
            "intent": "greeting",
            "classify_ns": raw.get("classify_ns"),
        }
    elif event_id == "play_uri_invocation":
        play_uri = raw.get("play_uri")
        derived["onboarding"] = {
            "intent": "play_uri",
            "play_uri": play_uri,
            "classify_ns": raw.get("classify_ns"),
        }
        derived["match"] = {"reference": play_uri}
        derived["request"] = {"parameters": dict(raw.get("parameters", {}))}
    elif event_id == "outcome_play_invocation":
        intent = raw.get("intent")
        derived["onboarding"] = {"classify_ns": raw.get("classify_ns")}
        derived["request"] = {"intent": intent, "requested_outcome": intent}
        derived["modality_policy"] = {
            "mode": "auto",
            "allowed": ["call", "shell", "drive"],
            "forbidden": [],
            "widening_requires_approval": True,
        }
    elif event_id == "play_search_invocation":
        derived["onboarding"] = {"classify_ns": raw.get("classify_ns")}
        derived["request"] = {"intent": raw.get("intent")}
    elif event_id == "play_awareness_invocation":
        intent = raw.get("intent")
        derived["onboarding"] = {"classify_ns": raw.get("classify_ns")}
        derived["request"] = {"intent": intent}
        derived["awareness"] = {"window_days": raw.get("window_days", 7)}
    elif event_id == "ordinary_play_invocation":
        derived["onboarding"] = {"classify_ns": raw.get("classify_ns")}
    elif event_id == "settled_task_invocation":
        intent = raw.get("intent")
        derived["onboarding"] = {"classify_ns": raw.get("classify_ns")}
        derived["request"] = {"intent": intent, "requested_outcome": intent}
    elif event_id in {"play_inspected", "play_not_runnable"}:
        # The card is advisory: an inspection without one still satisfies the contract.
        card = raw.get("audit_card")
        verdict = raw.get("audit_verdict")
        derived["audit_card"] = card if isinstance(card, str) else ""
        derived["audit_verdict"] = verdict if isinstance(verdict, str) and verdict.strip() else "not assessed"
    elif event_id == "play_reference_unresolved":
        error = raw.get("error")
        if isinstance(error, Mapping):
            derived["reason"] = error.get("message")
    elif event_id == "associated_credentials_invalid":
        # The invalid event requires a reason; a gate result that reached this
        # branch without one must block with a named cause, never crash.
        error = raw.get("error")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = (
                error.get("message")
                if isinstance(error, Mapping) and isinstance(error.get("message"), str)
                else None
            ) or "credential contract check did not verify"
        derived["reason"] = reason
        derived.setdefault("failure_class", "contract_check_failed")
        derived.setdefault("credential_names", [])
        derived.setdefault("evidence_refs", [])
    elif event_id in {"awareness_ready", "awareness_unchanged"}:
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
        digest_ref = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        ranking = raw.get("ranking")
        public_play_count = (
            ranking.get("eligible_count", 0) if isinstance(ranking, Mapping) else 0
        )
        play_choices = []
        sample = raw.get("public_sample")
        if isinstance(sample, list):
            for item in sample:
                if not isinstance(item, Mapping):
                    continue
                reference = item.get("reference")
                name = item.get("name")
                if not isinstance(reference, str) or not reference:
                    continue
                if not isinstance(name, str) or not name:
                    continue
                description = str(item.get("description") or "Inspect this Play.")
                downloads = item.get("download_count")
                if isinstance(downloads, int):
                    description = f"{description} · {downloads} lifetime downloads"
                recent_at = item.get("recent_at")
                recent_kind = item.get("recent_kind")
                if isinstance(recent_at, str) and recent_at:
                    date = recent_at.split("T", 1)[0]
                    published_label = (
                        "released" if recent_kind == "release" else "published"
                    )
                    description = f"{description} · {published_label} {date}"
                parameters = item.get("parameters")
                play_choices.append(
                    {
                        "reference": reference.partition("@")[0],
                        "label": name,
                        "description": description,
                        "parameters": (
                            dict(parameters) if isinstance(parameters, Mapping) else {}
                        ),
                    }
                )
        sample_contract = raw.get("sample")
        derived["awareness"] = {
            "complete": raw.get("complete") is True,
            "digest_ref": digest_ref,
            "coverage": (
                "complete"
                if isinstance(ranking, Mapping) and ranking.get("complete") is True
                else "partial"
            ),
            "public_play_count": public_play_count,
            "sample_strategy": (
                sample_contract.get("strategy")
                if isinstance(sample_contract, Mapping)
                else "random"
            ),
            "sample_limit": (
                sample_contract.get("limit")
                if isinstance(sample_contract, Mapping)
                else 10
            ),
            "sampled_count": len(play_choices),
            "play_choices": play_choices,
        }
        derived["evidence_refs"] = [digest_ref]
        derived["presentation_markdown"] = render_digest_markdown(dict(raw))
    elif event_id == "saved_play_inspected":
        identity = raw.get("identity")
        if not isinstance(identity, Mapping):
            raise ControllerRuntimeError("saved Play inspection identity is missing")
        exact_reference = raw.get("exact_reference")
        disclosure_sha256 = raw.get("disclosure_sha256")
        if not isinstance(exact_reference, str) or not exact_reference:
            raise ControllerRuntimeError("saved Play exact reference is missing")
        if not isinstance(disclosure_sha256, str) or not disclosure_sha256:
            raise ControllerRuntimeError("saved Play inspection digest is missing")
        canonical_reference = exact_reference.rsplit("@", 1)[0]
        derived["publication"] = {
            "canonical_reference": canonical_reference,
            "title": identity.get("name"),
            "description": identity.get("description"),
            "content_hash": identity.get("content_hash"),
            "inspect_ref": f"sha256:{disclosure_sha256}",
        }
        derived["play"] = {"version": identity.get("version")}
    return derived


def _render_command(command: str, context: Mapping[str, Any], root: Path) -> list[str]:
    rendered: list[str] = []
    for token in shlex.split(command):
        def replace(match: re.Match[str]) -> str:
            value = _path_value(context, match.group(1))
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise ControllerRuntimeError(
                    f"cannot render deterministic command field {match.group(1)}"
                )
            return str(value)

        rendered.append(_PLACEHOLDER.sub(replace, token))
    executable = Path(rendered[0])
    if not executable.is_absolute():
        executable = (root / executable).resolve()
    try:
        executable.relative_to(root.resolve())
    except ValueError as error:
        raise ControllerRuntimeError("deterministic action escaped the Play root") from error
    rendered[0] = str(executable)
    return rendered


def _select_event(
    action_id: str, raw: Mapping[str, Any], projection: Mapping[str, Any]
) -> str:
    accepted = projection.get("accepted_events", {})
    declared = raw.get("event")
    if isinstance(declared, str) and declared in accepted:
        return declared
    if action_id == "classify_play_invocation":
        return {
            "greeting": "empty_play_invocation",
            "play_uri": "play_uri_invocation",
            "outcome": "outcome_play_invocation",
            "search": "play_search_invocation",
            "awareness": "play_awareness_invocation",
            "settled": "settled_task_invocation",
            "settle_rejected": "settled_task_rejected",
            "ordinary": "ordinary_play_invocation",
        }.get(str(raw.get("invocation_kind")), "action_blocked")
    if action_id == "probe_rote_for_onboarding":
        return "rote_available" if raw.get("rote_status") == "installed" else "rote_missing"
    if action_id == "inspect_onboarding_identity":
        return (
            "onboarding_identity_ready"
            if raw.get("identity_status") == "authenticated"
            else "onboarding_identity_setup_required"
        )
    if action_id == "inspect_onboarding_experience":
        return (
            "onboarding_returning"
            if raw.get("experience_status") == "returning"
            else "onboarding_first_use"
        )
    if action_id == "inspect_registry_play":
        preflight = raw.get("preflight")
        return (
            "play_inspected"
            if isinstance(preflight, Mapping) and preflight.get("run_eligible") is True
            else "play_not_runnable"
        )
    if action_id == "collect_awareness_digest":
        memory = raw.get("memory")
        return (
            "awareness_unchanged"
            if isinstance(memory, Mapping) and memory.get("status") == "unchanged"
            else "awareness_ready"
        )
    if action_id == "resolve_public_owner":
        publication = raw.get("publication")
        return (
            "public_owner_context_unavailable"
            if isinstance(publication, Mapping)
            and publication.get("owner_resolution") == "unavailable"
            else "public_owner_context_ready"
        )
    if action_id == "inspect_publication_credentials":
        # play-publication-gate reports credential_status at the top level of
        # its result; older fixtures nested it under publication_validation.
        # Accept both so a verified gate is never routed to the invalid event.
        validation = raw.get("publication_validation")
        status = (
            validation.get("credential_status")
            if isinstance(validation, Mapping)
            else raw.get("credential_status")
        )
        return (
            "associated_credentials_verified"
            if status == "verified"
            else "associated_credentials_invalid"
        )
    success = [event for event in accepted if event != "action_blocked"]
    if len(success) == 1:
        return success[0]
    raise ControllerRuntimeError(
        f"deterministic action {action_id} needs an explicit result selector"
    )


def _build_payload(
    required: list[str], raw: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    # A contract may require both an object and fields nested beneath it. Build
    # parents first so a later child assignment cannot be erased by assigning
    # the parent object afterward (for example authentication plus its validated
    # receipt_ref and receipt_valid fields).
    ordered = sorted(enumerate(required), key=lambda item: (item[1].count("."), item[0]))
    for _, path in ordered:
        value = _result_value(raw, context, path)
        if value is _MISSING:
            raise ControllerRuntimeError(
                f"deterministic action result is missing required field {path}"
            )
        _set_path(payload, path, value)
    return payload


_MISSING = object()


def _result_value(
    raw: Mapping[str, Any], context: Mapping[str, Any], path: str
) -> Any:
    value = _path_value(raw, path, _MISSING)
    if value is not _MISSING:
        return value
    for candidate in (path.replace(".", "_"), path.rsplit(".", 1)[-1]):
        if candidate in raw:
            return raw[candidate]
    return _path_value(context, path, _MISSING)


def _path_value(
    payload: Mapping[str, Any], path: str, default: Any = None
) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    current = payload
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _presentation(raw: Mapping[str, Any]) -> Any | None:
    for key in ("presentation_markdown", "welcome_markdown", "orientation_markdown"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    presentation = raw.get("presentation")
    if isinstance(presentation, Mapping):
        markdown = presentation.get("markdown")
        if isinstance(markdown, str) and markdown:
            return markdown
    return presentation
