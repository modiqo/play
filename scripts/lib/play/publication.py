"""Build a verified Play publication readout and paste-ready social copy."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from .digest_state import stable_sha


SCHEMA = "play.publication-presentation/v1"
X_LIMIT = 280


class PublicationPresentationError(ValueError):
    """Publication metadata is incomplete or unsafe to present."""


def _flatten_controller_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept either the action's full controller context or its flat CLI fixture."""

    publication = payload.get("publication")
    play = payload.get("play")
    validation = payload.get("publication_validation")
    if not isinstance(publication, dict):
        return payload
    flattened = {
        "title": publication.get("title"),
        "description": publication.get("description"),
        "canonical_reference": publication.get("canonical_reference"),
        "version": play.get("version") if isinstance(play, dict) else publication.get("version"),
        "visibility": publication.get("visibility"),
        "owner": publication.get("owner"),
        "content_hash": publication.get("content_hash"),
        "play_uri": publication.get("uri"),
        "install_uri": publication.get("install_uri"),
        "credential_status": (
            validation.get("credential_status") if isinstance(validation, dict) else None
        ),
        "smoke_status": validation.get("smoke_status") if isinstance(validation, dict) else None,
        "smoke_exact_reference": (
            validation.get("smoke_exact_reference") if isinstance(validation, dict) else None
        ),
        "smoke_ns": validation.get("smoke_ns") if isinstance(validation, dict) else None,
    }
    return flattened


def _string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PublicationPresentationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PublicationPresentationError(f"{field} must be null or a non-empty string")
    return value.strip()


def _https_url(payload: dict[str, Any], field: str, *, required: bool) -> str | None:
    value = _string(payload, field) if required else _optional_string(payload, field)
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise PublicationPresentationError(f"{field} must be an absolute HTTPS URL")
    return value


def _exact_reference(reference: str, version: str) -> str:
    suffix = f"@{version}"
    return reference if reference.endswith(suffix) else f"{reference}{suffix}"


def _x_copy(title: str, description: str, play_uri: str) -> str:
    suffix = f"\n\n{play_uri}"
    available = X_LIMIT - len(suffix)
    if available < 2:
        raise PublicationPresentationError("play_uri is too long for paste-ready X copy")
    body = (
        f"My agent and I co-created {title} from a real run, capturing what worked, "
        f"what failed, and what we learned. {description}"
    )
    if len(body) > available:
        body = body[: available - 1].rstrip() + "…"
    return body + suffix


def _team_copy(title: str, description: str, owner: str, play_uri: str) -> str:
    return (
        "My agent and I co-created a private Play from a real run, capturing "
        "what worked, what failed, and what we learned.\n\n"
        f"{description}\n\n"
        f"Open it: {play_uri}\n\n"
        f"The {owner} team can open it. Ask me to add you if you need access."
    )


def build_publication_presentation(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic publication summary after canonical readback."""

    payload = _flatten_controller_context(payload)
    title = _string(payload, "title")
    description = _string(payload, "description")
    canonical_reference = _string(payload, "canonical_reference")
    version = _string(payload, "version")
    visibility = _string(payload, "visibility")
    if visibility not in {"private", "public"}:
        raise PublicationPresentationError("visibility must be private or public")
    owner = _string(payload, "owner")
    content_hash = _string(payload, "content_hash")
    play_uri = _https_url(payload, "play_uri", required=True)
    install_uri = _https_url(payload, "install_uri", required=visibility == "public")
    exact_reference = _exact_reference(canonical_reference, version)
    credential_status = _string(payload, "credential_status")
    smoke_status = _string(payload, "smoke_status")
    smoke_exact_reference = _optional_string(payload, "smoke_exact_reference")
    smoke_ns = payload.get("smoke_ns")
    if smoke_ns is not None and (
        not isinstance(smoke_ns, int) or isinstance(smoke_ns, bool) or smoke_ns < 0
    ):
        raise PublicationPresentationError("smoke_ns must be null or a non-negative integer")
    if visibility == "public":
        if credential_status != "verified" or smoke_status != "verified":
            raise PublicationPresentationError(
                "public presentation requires verified credential contracts and canonical smoke run"
            )
        if smoke_exact_reference != play_uri:
            raise PublicationPresentationError(
                "public smoke reference must equal the registry-returned Play URI"
            )
        if smoke_ns is None:
            raise PublicationPresentationError("public smoke latency is required")
        assert isinstance(smoke_ns, int)
    elif credential_status != "not_required" or smoke_status != "not_required":
        raise PublicationPresentationError(
            "private presentation requires publication validation to be not_required"
        )

    share_copy: dict[str, str | None] = {
        "team": None,
        "x": None,
        "linkedin": None,
    }
    lines = [
        "Published Play",
        "",
        f"- Canonical reference: `{exact_reference}`",
        f"- Visibility: {visibility}",
        f"- Owner: {owner}",
        f"- Content hash: `{content_hash}`",
    ]
    if visibility == "public":
        assert play_uri is not None and install_uri is not None and isinstance(smoke_ns, int)
        share_copy["x"] = _x_copy(title, description, play_uri)
        share_copy["linkedin"] = (
            f"My agent and I co-created {title} from a real run, capturing what worked, "
            "what failed, and what we learned.\n\n"
            f"{description}\n\n"
            "Others can inspect the method, run it, and improve it.\n\n"
            f"View the Play: {play_uri}\n"
            f"Install or bootstrap it: {install_uri}"
        )
        lines[2:2] = [
            f"- Play page: [{title} — {description}]({play_uri})",
            f"- Install/bootstrap: [Install {title}]({install_uri})",
            "- Associated credential contracts: verified",
            f"- Canonical public smoke: verified ({smoke_ns / 1_000_000:.2f} ms)",
        ]
        lines.extend(
            [
                "",
                "Paste for X:",
                "",
                "```text",
                share_copy["x"],
                "```",
                "",
                "Paste for LinkedIn:",
                "",
                "```text",
                share_copy["linkedin"],
                "```",
            ]
        )
    else:
        assert play_uri is not None
        share_copy["team"] = _team_copy(title, description, owner, play_uri)
        lines[2:2] = [
            f"- Private Play page: [{title} — {description}]({play_uri})",
            f"- Access: authorized members of {owner}",
        ]
        lines.extend(
            [
                "",
                "Share privately",
                "",
                "Add the recipient to the team if they do not already have access.",
                "",
                "Paste to your team:",
                "",
                "```text",
                share_copy["team"],
                "```",
            ]
        )

    result = {
        "schema": SCHEMA,
        "title": title,
        "description": description,
        "canonical_reference": exact_reference,
        "version": version,
        "visibility": visibility,
        "owner": owner,
        "content_hash": content_hash,
        "play_uri": play_uri,
        "install_uri": install_uri,
        "credential_status": credential_status,
        "smoke_status": smoke_status,
        "smoke_exact_reference": smoke_exact_reference,
        "smoke_ns": smoke_ns,
        "share_copy": share_copy,
        "markdown": "\n".join(lines),
    }
    result["presentation_ref"] = stable_sha(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise PublicationPresentationError("input must be a JSON object")
        result = build_publication_presentation(payload)
    except (json.JSONDecodeError, PublicationPresentationError) as error:
        print(f"play-publication: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
