"""Deterministic Play invocation, identity, welcome, and public-card helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .private_store import PrivateStoreError, atomic_write_json, load_json, locked_store
from .render import json_text
from .sidekick import latest_hook, load_ledger
from .state_home import state_path


SCHEMA = "play.onboarding/v1"
CARD_SCHEMA = "rote.play.v1"
PLAY_HOST = "play.modiqo.ai"
MAX_CARD_BYTES = 200_000
ONBOARDING_STATE_SCHEMA = "play.onboarding-state/v1"
ONBOARDING_ORIENTATION_VERSION = 3
def default_onboarding_state_path() -> Path:
    return state_path("onboarding-state.json")

STARTER_PLAY_REFERENCE = "modiqo/hello@0.1.0"
STARTER_PLAY_URI = "https://play.modiqo.ai/modiqo/hello@0.1.0"
_PLAY_PREFIX = re.compile(r"^(?:\$play|/play)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_SETTLE_REQUEST = re.compile(
    r"^(?:\$play|/play)\s+settle\b(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL
)
_STARTER_RUN = re.compile(
    r"^(?:(?:please\s+)?run\s+(?:the\s+)?hello(?:\s+play)?|(?:\$play|/play)\s+run\s+hello)[.!]?$",
    re.IGNORECASE,
)
_ACTIVATION_ONLY = {
    'user activated the skill "play". follow the loaded skill instructions.',
    "user activated the skill 'play'. follow the loaded skill instructions.",
    'the user has activated the "play" skill.',
    "the user has activated the 'play' skill.",
}
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_NAME_VERSION = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:@[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)?$"
)
_OK_EMAIL = re.compile(r"(?im)^ok:\s*([^@\s]+@[^@\s]+\.[^@\s]+)$")
_SAFE_HUMAN_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_FAST_OUTCOME = re.compile(
    r"^(?:(?:please|kindly)\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"(?:(?:help\s+me|help)\s+)?"
    r"(?:retrieve|fetch|get|find|collect|download|export|list|summarize|check|"
    r"monitor|calculate|compare)\b",
    re.IGNORECASE,
)


class OnboardingError(RuntimeError):
    """An onboarding probe or public-card read failed safely."""


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OnboardingError(f"{label} is missing or malformed")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnboardingError(f"{label} is missing or malformed")
    return value.strip()


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def canonical_play_uri(value: str) -> str | None:
    """Return a safe canonical public Play URI, or None for any other URL/text."""

    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != PLAY_HOST
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) != 2 or not _SLUG.fullmatch(segments[0]) or not _NAME_VERSION.fullmatch(segments[1]):
        return None
    return value.strip()


def _play_uri_request(value: str) -> tuple[str, dict[str, str]] | None:
    """Parse one canonical Play URI followed only by explicit key=value parameters."""

    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if not parts:
        return None
    uri = canonical_play_uri(parts[0])
    if uri is None:
        return None
    parameters: dict[str, str] = {}
    for token in parts[1:]:
        name, separator, parameter_value = token.partition("=")
        if (
            not separator
            or not _PARAMETER_NAME.fullmatch(name)
            or not parameter_value
            or name in parameters
        ):
            return None
        parameters[name] = parameter_value
    return uri, parameters


def _canonical_play_action_uri(value: object, label: str) -> str:
    uri = _string(value, label)
    try:
        parsed = urlparse(uri)
        port = parsed.port
    except ValueError as error:
        raise OnboardingError(f"{label} is malformed") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != PLAY_HOST
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise OnboardingError(f"{label} must remain on the canonical Play HTTPS host")
    return uri


def classify_invocation(original: str) -> dict[str, Any]:
    """Classify exact aliases, URI runs, and unambiguous outcome requests."""

    started = time.perf_counter_ns()
    stripped = original.strip()
    settle_match = _SETTLE_REQUEST.fullmatch(stripped)
    if settle_match is not None:
        return _classify_settled(
            (settle_match.group(1) or "").strip(), started=started
        )
    match = _PLAY_PREFIX.fullmatch(stripped)
    candidate = (match.group(1) or "").strip() if match is not None else stripped
    uri_request = _play_uri_request(candidate)
    parameters: dict[str, str] = {}
    if stripped.casefold() in _ACTIVATION_ONLY:
        kind = "greeting"
        play_uri = None
    elif _STARTER_RUN.fullmatch(stripped):
        kind = "play_uri"
        play_uri = STARTER_PLAY_URI
    elif match is not None:
        remainder = (match.group(1) or "").strip()
        if not remainder:
            kind = "greeting"
            play_uri = None
        elif uri_request is not None:
            kind = "play_uri"
            play_uri, parameters = uri_request
        elif _FAST_OUTCOME.match(remainder):
            kind = "outcome"
            play_uri = None
        else:
            play_uri = None
            kind = "ordinary"
    elif uri_request is not None:
        kind = "play_uri"
        play_uri, parameters = uri_request
    elif _FAST_OUTCOME.match(stripped):
        kind = "outcome"
        play_uri = None
    else:
        play_uri = None
        kind = "ordinary"
    return {
        "schema": SCHEMA,
        "kind": "invocation",
        "ok": True,
        "invocation_kind": kind,
        "play_uri": play_uri,
        "parameters": parameters,
        "intent": candidate.rstrip(".!?"),
        "preferences": {"policies": load_ledger()},
        "classify_ns": time.perf_counter_ns() - started,
    }


def _classify_settled(summary: str, *, started: int) -> dict[str, Any]:
    """Classify the post-task save-hook re-entry without qualification or search."""

    hook = latest_hook()
    intent = summary or (hook or {}).get("intent") or "settled task"
    return {
        "schema": SCHEMA,
        "kind": "invocation",
        "ok": True,
        "invocation_kind": "settled",
        "play_uri": None,
        "parameters": {},
        "intent": intent,
        "standby": {
            "armed": hook is not None,
            "task_class": (hook or {}).get("task_class"),
            "hook_ref": (hook or {}).get("hook_ref"),
            "settle_summary": summary or None,
        },
        "preferences": {"policies": load_ledger()},
        "classify_ns": time.perf_counter_ns() - started,
    }


def classify_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = _object(payload.get("request"), "request")
    original = request.get("original")
    if not isinstance(original, str):
        raise OnboardingError("request.original must be a string")
    return classify_invocation(original)


def probe_rote() -> dict[str, Any]:
    """Probe the live machine for Rote without invoking it."""

    started = time.perf_counter_ns()
    discovered = shutil.which("rote")
    off_path = False
    if discovered is None:
        for candidate in (
            Path.home() / ".local" / "bin" / "rote",
            Path.home() / ".cargo" / "bin" / "rote",
        ):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                discovered = str(candidate)
                off_path = True
                break
    return {
        "schema": SCHEMA,
        "kind": "rote_probe",
        "ok": True,
        "rote_status": "installed" if discovered else "missing",
        "rote_command": discovered,
        "rote_off_path": off_path,
        "probe_ns": time.perf_counter_ns() - started,
    }


def _validated_rote_command(value: object) -> str:
    command = _string(value, "onboarding.rote_command")
    path = Path(command)
    if path.name != "rote" or not path.is_file() or not os.access(path, os.X_OK):
        resolved = shutil.which(command) if command == "rote" else None
        if resolved is None:
            raise OnboardingError("the probed Rote command is no longer executable")
        return resolved
    return command


def _warm_caches_after_identity() -> None:
    """Detached, best-effort warm-up of the inbox and hub catalog after sign-in.

    Fires the moment an authenticated identity is verified so a first-time user's
    catalog, interception index, and what's-new inbox populate in the background
    without waiting for the next session start. Never blocks or fails identity.
    """

    if os.environ.get("PLAY_SKIP_CACHE_WARMUP") == "1":
        return
    refresher = Path(__file__).resolve().parents[2] / "bin" / "play-inbox"
    if not refresher.is_file():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(refresher), "refresh", "--if-older-than", "6"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def inspect_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run whoami only after the binary probe and return email metadata, never auth tokens."""

    started = time.perf_counter_ns()
    onboarding = _object(payload.get("onboarding"), "onboarding")
    command = _validated_rote_command(onboarding.get("rote_command"))
    try:
        completed = subprocess.run(
            [command, "whoami"],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OnboardingError("Rote identity probe failed") from error
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    email_match = _OK_EMAIL.search(completed.stdout or "")
    digest = hashlib.sha256(combined.encode()).hexdigest()
    if completed.returncode != 0 or email_match is None:
        return {
            "schema": SCHEMA,
            "kind": "identity",
            "ok": True,
            "identity_status": "setup_required",
            "email": None,
            "email_handle": None,
            "identity_ref": f"sha256:{digest}",
            "whoami_ns": time.perf_counter_ns() - started,
        }
    email = email_match.group(1).strip().lower()
    handle = email.split("@", 1)[0]
    _warm_caches_after_identity()
    return {
        "schema": SCHEMA,
        "kind": "identity",
        "ok": True,
        "identity_status": "authenticated",
        "email": email,
        "email_handle": handle,
        "identity_ref": f"sha256:{digest}",
        "whoami_ns": time.perf_counter_ns() - started,
    }


def _onboarding_identity_key(email: object) -> str:
    normalized = _string(email, "onboarding.email").lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _load_onboarding_state(path: Path) -> dict[str, Any]:
    try:
        state = load_json(path)
    except FileNotFoundError:
        return {"schema": ONBOARDING_STATE_SCHEMA, "identities": {}}
    except PrivateStoreError as error:
        raise OnboardingError(str(error)) from error
    if (
        not isinstance(state, dict)
        or state.get("schema") != ONBOARDING_STATE_SCHEMA
        or not isinstance(state.get("identities"), dict)
    ):
        raise OnboardingError(f"onboarding state must use {ONBOARDING_STATE_SCHEMA}")
    return state


def check_onboarding_experience(
    payload: Mapping[str, Any],
    *,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Classify an authenticated identity without storing its email address."""

    started = time.perf_counter_ns()
    if state_path is None:
        state_path = default_onboarding_state_path()
    onboarding = _object(payload.get("onboarding"), "onboarding")
    identity_key = _onboarding_identity_key(onboarding.get("email"))
    state = _load_onboarding_state(state_path)
    entry = state["identities"].get(identity_key)
    returning = (
        isinstance(entry, dict)
        and entry.get("orientation_version") == ONBOARDING_ORIENTATION_VERSION
        and isinstance(entry.get("shown_at"), str)
    )
    return {
        "schema": SCHEMA,
        "kind": "experience",
        "ok": True,
        "experience_status": "returning" if returning else "first_use",
        "experience_ref": f"sha256:{identity_key}",
        "orientation_version": ONBOARDING_ORIENTATION_VERSION,
        "experience_ns": time.perf_counter_ns() - started,
    }


def render_first_use_orientation(human_name: str) -> str:
    """Explain the human/agent/Rote bargain in short, concrete language."""

    return "\n".join(
        [
            f"# Hello, {human_name}.",
            "",
            "**Start small. See what happens. Stay in control.**",
            "",
            "A Play is a checked, reusable way to get a result. Rote inspects and runs it on your computer.",
            "",
            "The recommended first step is **Run Hello**. It uses public data only, needs no account or credentials, and declares no writes. You will see the Play before it runs and then get a real result.",
            "",
            "You can also tell me a goal, browse useful Plays, or leave. Nothing is downloaded or run without the approval required for that action.",
            "",
            "Create a team space when the work should outlive one person: claim a recognizable handle, invite colleagues to review and use Plays, and keep sensitive learning inside the team.",
            "",
            "The broader loop is **learn → teach → learn**. Your team learns from real work, publishes selected Plays to Community, and learns again from reuse and feedback. A verified Community publication includes paste-ready X and LinkedIn explanations; Play never posts them for you.",
            "",
            "If no Play fits later, we can work out the job together. You provide the goals, rules, and exceptions; I help test the method. You decide whether the result stays one-off, goes to your team, or teaches the Community.",
        ]
    )


def prepare_first_use_orientation(payload: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    onboarding = _object(payload.get("onboarding"), "onboarding")
    human_name = _safe_human_name(onboarding.get("email_handle")) or "friend"
    markdown = render_first_use_orientation(human_name)
    presentation_ref = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    return {
        "schema": SCHEMA,
        "kind": "first_use_orientation",
        "ok": True,
        "orientation_status": "presented",
        "orientation_version": ONBOARDING_ORIENTATION_VERSION,
        "orientation_markdown": markdown,
        "orientation_ref": presentation_ref,
        "starter_reference": STARTER_PLAY_URI,
        "orientation_ns": time.perf_counter_ns() - started,
        "presentation_markdown": markdown,
        "presentation_ref": presentation_ref,
    }


def remember_first_use_orientation(
    payload: Mapping[str, Any],
    *,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Remember only a hashed identity, version, and timestamp after presentation."""

    started = time.perf_counter_ns()
    if state_path is None:
        state_path = default_onboarding_state_path()
    onboarding = _object(payload.get("onboarding"), "onboarding")
    if onboarding.get("orientation_status") != "presented":
        raise OnboardingError("first-use orientation must be presented before it is remembered")
    identity_key = _onboarding_identity_key(onboarding.get("email"))
    try:
        with locked_store(state_path.parent):
            state = _load_onboarding_state(state_path)
            state["identities"][identity_key] = {
                "orientation_version": ONBOARDING_ORIENTATION_VERSION,
                "shown_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_write_json(state_path, state)
    except PrivateStoreError as error:
        raise OnboardingError(str(error)) from error
    return {
        "schema": SCHEMA,
        "kind": "first_use_marker",
        "ok": True,
        "orientation_status": "recorded",
        "orientation_version": ONBOARDING_ORIENTATION_VERSION,
        "experience_ref": f"sha256:{identity_key}",
        "marker_ns": time.perf_counter_ns() - started,
    }


def render_first_play_activation(human_name: str) -> str:
    return "\n".join(
        [
            f"# Your first Play is complete, {human_name}.",
            "",
            "You approved the Play, Rote ran it on this computer, and the full result above was checked.",
            "",
            "That is the basic pattern: ask for a result, inspect the method, approve the work, and keep what succeeds when you want to use it again.",
            "",
            "Your experience does not have to disappear when the task ends. A Play lets you keep what worked and pass it on when you choose.",
        ]
    )


def prepare_first_play_activation(payload: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    onboarding = _object(payload.get("onboarding"), "onboarding")
    if onboarding.get("starter_status") != "completed":
        raise OnboardingError("first Play activation requires a completed starter Play")
    human_name = _safe_human_name(onboarding.get("email_handle")) or "friend"
    markdown = render_first_play_activation(human_name)
    presentation_ref = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    return {
        "schema": SCHEMA,
        "kind": "first_play_activation",
        "ok": True,
        "activation_status": "presented",
        "activation_markdown": markdown,
        "activation_ref": presentation_ref,
        "activation_ns": time.perf_counter_ns() - started,
        "presentation_markdown": markdown,
        "presentation_ref": presentation_ref,
    }


def render_team_loop(team_name: str, team_slug: str) -> str:
    """Explain the reusable team-to-community sharing loop without claiming effects."""

    return "\n".join(
        [
            f"# Team space ready: {team_name}",
            "",
            f"Team handle: `{team_slug}`",
            "",
            "Invite colleagues to review, improve, and use Plays together. Team publication keeps the Play inside the authorized organization.",
            "",
            "When a verified Play teaches something worth sharing, choose **Community** after creation. Play will publish only with approval, verify the exact public URI, and produce paste-ready X and LinkedIn explanations of what it does.",
            "",
            "That creates the loop: **learn in real work → teach the team or Community → learn from reuse and feedback**.",
            "",
            "Nothing has been published to Community or posted to social media by this orientation.",
        ]
    )


def prepare_team_loop(payload: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    team = _object(payload.get("team"), "team")
    team_slug = _string(team.get("slug"), "team.slug")
    team_name = _string(team.get("name"), "team.name")
    markdown = render_team_loop(team_name, team_slug)
    presentation_ref = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    return {
        "schema": SCHEMA,
        "kind": "team_loop",
        "ok": True,
        "team": {"status": "presented", "presentation_ref": presentation_ref},
        "presentation_markdown": markdown,
        "presentation_ref": presentation_ref,
        "render_ns": time.perf_counter_ns() - started,
    }


def _safe_human_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _SAFE_HUMAN_NAME.sub(" ", value.strip())
    normalized = " ".join(normalized.split())[:80].strip()
    return normalized or None


def render_exploration_welcome(human_name: str) -> str:
    """Render the stable human-as-expert exploration welcome."""

    return (
        f"Welcome, {human_name}. You are the expert in this work. I bring broad knowledge and "
        "the ability to search, use tools, and test steps, but I cannot know the local rules, "
        "exceptions, and standards that experience has taught you. I am your apprentice: ask "
        "me to watch, question, and follow your steering. If we find a repeatable method that "
        "works, Rote can save it as a Play for you, your team, or the community—only when you choose."
    )


def prepare_exploration_welcome(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a bounded human name and prepare the typed Explore welcome."""

    started = time.perf_counter_ns()
    onboarding = payload.get("onboarding")
    identity_status = "unavailable"
    identity_source = "neutral_fallback"
    identity_ref: str | None = None
    human_name: str | None = None

    if isinstance(onboarding, dict) and onboarding.get("identity_status") == "authenticated":
        human_name = _safe_human_name(onboarding.get("email_handle"))
        candidate_ref = onboarding.get("identity_ref")
        identity_ref = candidate_ref if isinstance(candidate_ref, str) else None
        if human_name is not None:
            identity_status = "authenticated"
            identity_source = "onboarding_email_handle"

    if human_name is None:
        probe = probe_rote()
        if probe["rote_status"] == "installed":
            try:
                identity = inspect_identity(
                    {"onboarding": {"rote_command": probe["rote_command"]}}
                )
            except OnboardingError as error:
                identity_ref = f"sha256:{hashlib.sha256(str(error).encode()).hexdigest()}"
            else:
                identity_ref = identity["identity_ref"]
                human_name = _safe_human_name(identity.get("email_handle"))
                if identity["identity_status"] == "authenticated" and human_name is not None:
                    identity_status = "authenticated"
                    identity_source = "live_email_handle"

    display_name = human_name or "friend"
    markdown = render_exploration_welcome(display_name)
    presentation_ref = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    return {
        "schema": SCHEMA,
        "kind": "exploration_welcome",
        "ok": True,
        "exploration": {
            "welcome_status": "presented",
            "human_name": human_name,
            "identity_status": identity_status,
            "identity_source": identity_source,
            "identity_ref": identity_ref,
            "welcome_markdown": markdown,
            "welcome_ref": presentation_ref,
            "resolve_ns": time.perf_counter_ns() - started,
        },
        "presentation_markdown": markdown,
        "presentation_ref": presentation_ref,
    }


def _card_requirements(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    requirements = card.get("requirements")
    adapters = requirements.get("adapters") if isinstance(requirements, dict) else None
    normalized: list[dict[str, Any]] = []
    if not isinstance(adapters, list):
        return normalized
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        demand = adapter.get("credentialDemand")
        raw_credentials = demand.get("requirements") if isinstance(demand, dict) else None
        names = []
        protocols = []
        if isinstance(raw_credentials, list):
            for credential in raw_credentials:
                if not isinstance(credential, dict):
                    continue
                name = credential.get("name")
                protocol = credential.get("protocol")
                if isinstance(name, str) and name:
                    names.append(name)
                if isinstance(protocol, str) and protocol:
                    protocols.append(protocol)
        normalized.append(
            {
                "id": adapter.get("id"),
                "display_name": adapter.get("displayName") or adapter.get("id"),
                "requirement": adapter.get("requirement"),
                "credential_status": demand.get("status") if isinstance(demand, dict) else "unknown",
                "credential_names": sorted(set(names)),
                "credential_protocols": sorted(set(protocols)),
            }
        )
    return normalized


def _card_parameters(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = card.get("parameters")
    if not isinstance(raw, list):
        return []
    parameters = []
    for parameter in raw:
        if not isinstance(parameter, dict) or not isinstance(parameter.get("name"), str):
            continue
        parameters.append(
            {
                "name": parameter["name"],
                "type": parameter.get("type") or "unknown",
                "required": parameter.get("required") is True,
                "default": parameter.get("default"),
                "description": parameter.get("description") or "",
            }
        )
    return parameters


def normalize_card(uri: str, card: Mapping[str, Any], fetch_ns: int) -> dict[str, Any]:
    if card.get("schema") != CARD_SCHEMA or card.get("type") != "play":
        raise OnboardingError("public URI did not return a rote.play.v1 card")
    card_id = _string(card.get("id"), "card.id")
    # The registry serves versionless URIs by pinning them: /owner/name returns a
    # card whose id is /owner/name@<current-version>. Accept that pinning; reject
    # any other identity drift (different owner or name fails closed).
    requested_is_versionless = "@" not in uri.rsplit("/", 1)[-1]
    if card_id != uri and not (
        requested_is_versionless and card_id.startswith(f"{uri}@")
    ):
        raise OnboardingError("public card id does not match the requested Play URI")
    actions = _object(card.get("actions"), "card.actions")
    inspect_action = _object(actions.get("inspect"), "card.actions.inspect")
    bootstrap_action = _object(
        actions.get("bootstrapAndRun"), "card.actions.bootstrapAndRun"
    )
    install_action = _object(actions.get("installCliOnly"), "card.actions.installCliOnly")
    if inspect_action.get("effect") != "read-only":
        raise OnboardingError("public card inspection action is not declared read-only")
    if (
        bootstrap_action.get("requiresConsent") is not True
        or install_action.get("requiresConsent") is not True
    ):
        raise OnboardingError("public card install actions must require explicit consent")
    inspect_command = _string(inspect_action.get("command"), "card inspect command")
    if inspect_command not in {
        f"rote play inspect {card_id}",
        f"rote play inspect {card_id} --json",
    }:
        raise OnboardingError("public card inspect command does not match the requested URI")
    normalized = {
        "schema": CARD_SCHEMA,
        "uri": card_id,
        "title": _string(card.get("title") or card.get("name"), "card.title"),
        "description": _string(card.get("description"), "card.description"),
        "reference": _string(card.get("reference"), "card.reference"),
        "version": _string(card.get("version"), "card.version"),
        "visibility": _string(card.get("visibility"), "card.visibility"),
        "inspect_command": inspect_command,
        "bootstrap_uri": _canonical_play_action_uri(
            bootstrap_action.get("href"), "card bootstrap URI"
        ),
        "install_uri": _canonical_play_action_uri(
            install_action.get("href"), "card install URI"
        ),
        "parameters": _card_parameters(card),
        "adapters": _card_requirements(card),
        "declared_writes": (
            card.get("effects", {}).get("declaredWrites", [])
            if isinstance(card.get("effects"), dict)
            else []
        ),
        "credentials_remain_local": (
            card.get("effects", {}).get("credentialsRemainLocal") is True
            if isinstance(card.get("effects"), dict)
            else False
        ),
        "fetch_ns": fetch_ns,
    }
    digest_source = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    normalized["card_sha256"] = hashlib.sha256(digest_source.encode()).hexdigest()
    return normalized


def fetch_public_card(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Curl one canonical Play host without redirects and normalize its JSON card."""

    started = time.perf_counter_ns()
    onboarding = _object(payload.get("onboarding"), "onboarding")
    supplied = _string(onboarding.get("play_uri"), "onboarding.play_uri")
    uri = canonical_play_uri(supplied)
    if uri is None:
        raise OnboardingError("only canonical https://play.modiqo.ai Play URIs may be fetched")
    curl = shutil.which("curl")
    if curl is None:
        raise OnboardingError("curl is required to read a public Play card without Rote")
    try:
        completed = subprocess.run(
            [curl, "-fsS", "--proto", "=https", "--max-time", "15", uri],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OnboardingError("public Play card fetch failed") from error
    if completed.returncode != 0:
        raise OnboardingError("public Play card fetch failed")
    if len(completed.stdout.encode()) > MAX_CARD_BYTES:
        raise OnboardingError("public Play card exceeds the size limit")
    try:
        card = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise OnboardingError("public Play URI returned malformed JSON") from error
    normalized = normalize_card(uri, _object(card, "public Play card"), time.perf_counter_ns() - started)
    return {
        "schema": SCHEMA,
        "kind": "public_card",
        "ok": True,
        "card": normalized,
    }


def render_card(card: Mapping[str, Any]) -> str:
    lines = [
        f"# {card['title']}",
        "",
        str(card["description"]),
        "",
        f"Reference: `{card['reference']}` · {card['visibility']}",
        "",
        "## What just happened",
        "",
        "You pasted a **Play URI** — a link to a saved, inspectable, runnable procedure that",
        "someone captured from real verified work. **Rote** is the local engine that runs Plays:",
        "it lives on your machine, your credentials stay local, and nothing executes without",
        "your explicit approval. This card is the Play's public description, fetched read-only —",
        "nothing has been installed or run.",
        "",
        "With Rote set up, the flow is always: **inspect** (read-only disclosure of parameters,",
        "adapters, credentials by name, and declared effects) → **approve** → **run** → verified",
        "result. Work you later find repeatable can become your own Play the same way.",
        "",
        "## Inspect or install Rote",
        "",
        "In an agent harness, installation is owned by the guided `rote-setup` skill — accept",
        "the next prompt and it walks through install and sign-in, then returns to this exact",
        "Play. The links below are for setting up outside a harness:",
        "",
        f"- Read-only inspection after Rote is installed: `{card['inspect_command']}`",
        f"- Guided bootstrap and run: {card['bootstrap_uri']}",
        f"- Install only the Rote CLI: {card['install_uri']}",
        "",
        "The install and bootstrap links execute downloaded setup code and still require your explicit consent.",
        "",
        "## Requirements",
        "",
    ]
    adapters = card.get("adapters")
    if isinstance(adapters, list) and adapters:
        for adapter in adapters:
            if not isinstance(adapter, dict):
                continue
            credentials = ", ".join(_strings(adapter.get("credential_names"))) or "none declared"
            lines.append(
                f"- `{adapter.get('id')}` ({adapter.get('requirement')}): credentials {credentials}"
            )
    else:
        lines.append("- No adapters declared.")
    lines.extend(["", "## Parameters", ""])
    parameters = card.get("parameters")
    if isinstance(parameters, list) and parameters:
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            requirement = "required" if parameter.get("required") is True else "optional"
            default = (
                f"; default `{parameter.get('default')}`"
                if parameter.get("default") is not None
                else ""
            )
            lines.append(
                f"- `{parameter.get('name')}`: {parameter.get('description') or parameter.get('type')} "
                f"({requirement}{default})"
            )
    else:
        lines.append("- None declared.")
    lines.extend(
        [
            "",
            "## Effects",
            "",
            f"- Declared writes: {len(card.get('declared_writes', []))}",
            f"- Credentials remain local: {'yes' if card.get('credentials_remain_local') else 'unknown'}",
        ]
    )
    return "\n".join(lines)


def present_card(payload: Mapping[str, Any]) -> dict[str, Any]:
    onboarding = _object(payload.get("onboarding"), "onboarding")
    card = _object(onboarding.get("card"), "onboarding.card")
    markdown = render_card(card)
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    return {
        "schema": SCHEMA,
        "kind": "public_card_presentation",
        "ok": True,
        "presentation_markdown": markdown,
        "presentation_ref": f"sha256:{digest}",
    }


def _read_payload() -> dict[str, Any]:
    try:
        return _object(json.load(sys.stdin), "onboarding input")
    except json.JSONDecodeError as error:
        raise OnboardingError("stdin must contain valid JSON") from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "classify",
            "probe",
            "identity",
            "experience",
            "present-first",
            "mark-first",
            "present-activation",
            "present-team",
            "explore-welcome",
            "card",
            "present-card",
        ),
    )
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.mode == "probe":
            result = probe_rote()
        else:
            if not args.stdin:
                parser.error(f"--stdin is required for {args.mode}")
            payload = _read_payload()
            if args.mode == "classify":
                result = classify_payload(payload)
            elif args.mode == "identity":
                result = inspect_identity(payload)
            elif args.mode == "experience":
                result = check_onboarding_experience(payload)
            elif args.mode == "present-first":
                result = prepare_first_use_orientation(payload)
            elif args.mode == "mark-first":
                result = remember_first_use_orientation(payload)
            elif args.mode == "present-activation":
                result = prepare_first_play_activation(payload)
            elif args.mode == "present-team":
                result = prepare_team_loop(payload)
            elif args.mode == "explore-welcome":
                result = prepare_exploration_welcome(payload)
            elif args.mode == "card":
                result = fetch_public_card(payload)
            else:
                result = present_card(payload)
    except OnboardingError as error:
        digest = hashlib.sha256(str(error).encode()).hexdigest()
        result = {
            "schema": SCHEMA,
            "kind": args.mode,
            "ok": False,
            "reason": str(error),
            "evidence_refs": [f"sha256:{digest}"],
        }
    print(json_text(result) if args.as_json else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
