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
    body = f"{title}: {description}"
    if len(body) > available:
        body = body[: available - 1].rstrip() + "…"
    return body + suffix


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
    play_uri = _https_url(payload, "play_uri", required=visibility == "public")
    install_uri = _https_url(payload, "install_uri", required=visibility == "public")
    exact_reference = _exact_reference(canonical_reference, version)

    share_copy: dict[str, str | None] = {"x": None, "linkedin": None}
    lines = [
        "Published Play",
        "",
        f"- Canonical reference: `{exact_reference}`",
        f"- Visibility: {visibility}",
        f"- Owner: {owner}",
        f"- Content hash: `{content_hash}`",
    ]
    if visibility == "public":
        assert play_uri is not None and install_uri is not None
        share_copy["x"] = _x_copy(title, description, play_uri)
        share_copy["linkedin"] = (
            f"I published {title} as a reusable Play.\n\n"
            f"{description}\n\n"
            f"View the Play: {play_uri}\n"
            f"Install or bootstrap it: {install_uri}"
        )
        lines[2:2] = [
            f"- Play page: [{title} — {description}]({play_uri})",
            f"- Install/bootstrap: [Install {title}]({install_uri})",
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
