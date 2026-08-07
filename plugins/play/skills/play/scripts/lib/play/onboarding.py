"""Deterministic Play invocation, greeting, identity, and public-card helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .render import json_text


SCHEMA = "play.onboarding/v1"
CARD_SCHEMA = "rote.play.v1"
PLAY_HOST = "play.modiqo.ai"
MAX_CARD_BYTES = 200_000
_PLAY_PREFIX = re.compile(r"^(?:\$play|/play)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_NAME_VERSION = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:@[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)?$"
)
_OK_EMAIL = re.compile(r"(?im)^ok:\s*([^@\s]+@[^@\s]+\.[^@\s]+)$")


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
    """Classify only the exact empty aliases and canonical Play URI forms."""

    started = time.perf_counter_ns()
    stripped = original.strip()
    match = _PLAY_PREFIX.fullmatch(stripped)
    if match is not None:
        remainder = (match.group(1) or "").strip()
        if not remainder:
            kind = "greeting"
            play_uri = None
        else:
            play_uri = canonical_play_uri(remainder)
            kind = "play_uri" if play_uri else "ordinary"
    else:
        play_uri = canonical_play_uri(stripped)
        kind = "play_uri" if play_uri else "ordinary"
    return {
        "schema": SCHEMA,
        "kind": "invocation",
        "ok": True,
        "invocation_kind": kind,
        "play_uri": play_uri,
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
    if card_id != uri:
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
    if inspect_command not in {f"rote play inspect {uri}", f"rote play inspect {uri} --json"}:
        raise OnboardingError("public card inspect command does not match the requested URI")
    normalized = {
        "schema": CARD_SCHEMA,
        "uri": uri,
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
        "## Inspect or install Rote",
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
    parser.add_argument("mode", choices=("classify", "probe", "identity", "card", "present-card"))
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
