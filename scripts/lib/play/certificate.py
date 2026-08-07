"""Render a verified Play birth certificate with trace learning and share copy."""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .birth import BirthError, resolve_birth, verify_birth
from .digest_state import stable_sha
from .publication import (
    PublicationPresentationError,
    build_publication_presentation,
)


SCHEMA = "play.birth-certificate-presentation/v1"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class CertificatePresentationError(ValueError):
    """The saved Play or owner-local birth cannot be certified truthfully."""


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CertificatePresentationError(f"{label} is missing or malformed")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CertificatePresentationError(f"{label} is missing or malformed")
    return value.strip()


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CertificatePresentationError(f"{label} must be a non-negative integer")
    return value


def _safe_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _SAFE_NAME.sub(" ", value.strip())
    normalized = " ".join(normalized.split())[:80].strip()
    return normalized or None


def _human_name(payload: Mapping[str, Any]) -> str:
    exploration = payload.get("exploration")
    if isinstance(exploration, dict):
        resolved = _safe_name(exploration.get("human_name"))
        if resolved is not None:
            return resolved
    onboarding = payload.get("onboarding")
    if isinstance(onboarding, dict):
        resolved = _safe_name(onboarding.get("email_handle"))
        if resolved is not None:
            return resolved
    return "friend"


def _trace_learning(record: Mapping[str, Any]) -> dict[str, Any]:
    journey = _object(record.get("journey"), "birth journey")
    commands = _nonnegative_int(journey.get("commands"), "journey.commands")
    responses = _nonnegative_int(journey.get("responses"), "journey.responses")
    raw_outcomes = journey.get("outcomes")
    outcomes = raw_outcomes if isinstance(raw_outcomes, dict) else {}
    successes = _nonnegative_int(outcomes.get("successes", 0), "outcomes.successes")
    errors = _nonnegative_int(outcomes.get("errors", 0), "outcomes.errors")
    unknown = _nonnegative_int(
        outcomes.get("unknown", max(0, commands - successes - errors)),
        "outcomes.unknown",
    )
    if successes + errors + unknown != commands:
        raise CertificatePresentationError(
            "trace outcome counts must equal the recorded command count"
        )
    edges = journey.get("dependency_edges")
    if not isinstance(edges, list):
        raise CertificatePresentationError("journey.dependency_edges must be an array")
    raw_modalities = journey.get("modalities")
    modalities = (
        sorted({item for item in raw_modalities if isinstance(item, str) and item})
        if isinstance(raw_modalities, list)
        else []
    )
    duration = journey.get("duration_seconds")
    if duration is not None and (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or duration < 0
    ):
        raise CertificatePresentationError(
            "journey.duration_seconds must be null or non-negative"
        )
    sources = _object(record.get("sources"), "birth sources")
    trace_method = _string(sources.get("trace"), "birth trace source")
    return {
        "commands": commands,
        "responses": responses,
        "successes": successes,
        "errors": errors,
        "unknown": unknown,
        "dependency_edges": len(edges),
        "modalities": modalities,
        "duration_seconds": duration,
        "trace_method": trace_method,
        "summary": (
            f"The redacted trace records {successes} successes, {errors} errors, and "
            f"{unknown} unknown outcomes across {commands} commands."
        ),
    }


def _meter(count: int, total: int, *, width: int = 16) -> str:
    filled = 0 if total == 0 else round(width * count / total)
    return "█" * filled + "·" * (width - filled)


def _plain_text(value: str) -> str:
    printable = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(printable.split())


def _markdown_label(value: str) -> str:
    return _plain_text(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _fenced(value: str, language: str = "text") -> list[str]:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}{language}", value, fence]


def _box(lines: list[str], *, width: int = 72) -> str:
    content_width = width - 4
    rendered: list[str] = []
    for raw_line in lines:
        line = _plain_text(raw_line)
        wrapped = textwrap.wrap(
            line,
            width=content_width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        rendered.extend(f"│ {item:<{content_width}} │" for item in wrapped)
    return "\n".join([f"╭{'─' * (width - 2)}╮", *rendered, f"╰{'─' * (width - 2)}╯"])


def _binding_for(
    index: Mapping[str, Any], sha: str, exact_reference: str
) -> dict[str, Any]:
    by_birth = _object(index.get("by_birth_sha"), "birth index")
    metadata = _object(by_birth.get(sha), "birth index metadata")
    references = metadata.get("exact_references")
    if not isinstance(references, list) or exact_reference not in references:
        raise CertificatePresentationError(
            "birth certificate is not bound to the verified exact Play reference"
        )
    bindings = _object(metadata.get("bindings"), "birth bindings")
    return _object(bindings.get(exact_reference), "exact birth binding")


def render_certificate(
    publication: Mapping[str, Any],
    *,
    sha: str,
    record: Mapping[str, Any],
    human_name: str,
    trace: Mapping[str, Any],
) -> str:
    title = _string(publication.get("title"), "publication title")
    description = _string(publication.get("description"), "publication description")
    exact_reference = _string(
        publication.get("canonical_reference"), "publication canonical reference"
    )
    visibility = _string(publication.get("visibility"), "publication visibility")
    owner = _string(publication.get("owner"), "publication owner")
    content_hash = _string(publication.get("content_hash"), "publication content hash")
    play_uri = publication.get("play_uri")
    install_uri = publication.get("install_uri")
    flow = _object(record.get("flow"), "birth flow")
    captured_at = _string(record.get("captured_at"), "birth captured_at")
    certificate_lines = [
        "PLAY BIRTH CERTIFICATE · VERIFIED",
        f"Play: {title}",
        f"Human domain expert: {human_name}",
        f"Published as: {exact_reference}",
        f"Visibility: {visibility}",
        f"Owner: {owner}",
        f"Content hash: {content_hash}",
        f"Play URI: {play_uri if isinstance(play_uri, str) else 'private — no public URI'}",
        f"Birth SHA: {sha}",
        f"Flow fingerprint: {_string(flow.get('fingerprint'), 'flow fingerprint')}",
        f"Captured: {captured_at}",
    ]
    total = _nonnegative_int(trace.get("commands"), "trace.commands")
    successes = _nonnegative_int(trace.get("successes"), "trace.successes")
    errors = _nonnegative_int(trace.get("errors"), "trace.errors")
    unknown = _nonnegative_int(trace.get("unknown"), "trace.unknown")
    modalities = trace.get("modalities")
    modality_text = ", ".join(modalities) if isinstance(modalities, list) else ""
    lines = [
        "# ✦ Play Birth Certificate",
        "",
        *_fenced(_box(certificate_lines)),
        "",
        "## Trace learning",
        "",
        f"- Successes: `{_meter(successes, total)}` **{successes}**",
        f"- Errors: `{_meter(errors, total)}` **{errors}**",
        f"- Unknown outcomes: `{_meter(unknown, total)}` **{unknown}**",
        f"- Commands / responses: **{total} / {trace['responses']}**",
        f"- Dependency edges: **{trace['dependency_edges']}**",
        f"- Modalities learned: **{modality_text or 'none detected'}**",
        f"- Trace evidence: `{trace['trace_method']}`",
        "",
        str(trace["summary"]),
    ]
    if isinstance(play_uri, str):
        lines.extend(
            [
                "",
                f"Play URI: [{_markdown_label(title)} — {_markdown_label(description)}]({play_uri})",
                f"Install/bootstrap: [Install {_markdown_label(title)}]({install_uri})",
                "Associated credential contracts: **verified**",
                f"Canonical public smoke: **verified** ({publication['smoke_ns'] / 1_000_000:.2f} ms)",
            ]
        )
    share_copy = _object(publication.get("share_copy"), "publication share copy")
    x_copy = share_copy.get("x")
    linkedin_copy = share_copy.get("linkedin")
    if isinstance(x_copy, str) and isinstance(linkedin_copy, str):
        lines.extend(
            [
                "",
                "## Share the certified Play",
                "",
                "X:",
                "",
                *_fenced(x_copy),
                "",
                "LinkedIn:",
                "",
                *_fenced(linkedin_copy),
            ]
        )
    lines.extend(
        [
            "",
            f"Dear {human_name}. It was a pleasure working with you, and we did an excellent job.",
        ]
    )
    return "\n".join(lines)


def build_certificate_presentation(
    payload: dict[str, Any], *, home: Path | None = None
) -> dict[str, Any]:
    """Verify and render one saved Play's bound owner-local birth certificate."""

    started = time.perf_counter_ns()
    publication = build_publication_presentation(payload)
    birth_context = _object(payload.get("birth"), "birth context")
    expected_sha = _string(birth_context.get("sha256"), "birth.sha256")
    sha, record, index = resolve_birth(expected_sha, home=home)
    if sha != expected_sha:
        raise CertificatePresentationError("resolved birth SHA does not match controller context")
    verification = verify_birth(expected_sha, home=home)
    if verification.get("valid") is not True:
        raise CertificatePresentationError("owner-local birth certificate verification failed")
    flow = _object(record.get("flow"), "birth flow")
    context_fingerprint = _string(
        birth_context.get("flow_fingerprint"), "birth.flow_fingerprint"
    )
    if context_fingerprint != flow.get("fingerprint"):
        raise CertificatePresentationError(
            "birth Flow fingerprint does not match controller context"
        )
    exact_reference = _string(
        publication.get("canonical_reference"), "publication canonical reference"
    )
    context_reference = _string(
        birth_context.get("exact_reference"), "birth.exact_reference"
    )
    if context_reference != exact_reference:
        raise CertificatePresentationError(
            "birth context reference does not match verified publication"
        )
    if _string(birth_context.get("binding_ref"), "birth.binding_ref") != exact_reference:
        raise CertificatePresentationError(
            "birth binding reference does not match verified publication"
        )
    context_content_hash = _string(
        birth_context.get("registry_content_hash"), "birth.registry_content_hash"
    )
    if context_content_hash != publication.get("content_hash"):
        raise CertificatePresentationError(
            "birth context content hash does not match verified publication"
        )
    binding = _binding_for(index, sha, exact_reference)
    if binding.get("registry_content_hash") != publication.get("content_hash"):
        raise CertificatePresentationError(
            "birth binding content hash does not match verified publication"
        )
    trace = _trace_learning(record)
    human_name = _human_name(payload)
    markdown = render_certificate(
        publication,
        sha=sha,
        record=record,
        human_name=human_name,
        trace=trace,
    )
    certificate_identity = {
        "birth_sha256": sha,
        "exact_reference": exact_reference,
        "content_hash": publication["content_hash"],
        "play_uri": publication["play_uri"],
    }
    certificate_ref = stable_sha(certificate_identity)
    birth_presentation = {
        "certificate_presented": True,
        "certificate_ref": certificate_ref,
        "trace_learning": trace,
    }
    presentation_identity = {
        "schema": SCHEMA,
        "certificate": certificate_identity,
        "birth": birth_presentation,
        "share_copy": publication["share_copy"],
        "presentation_markdown": markdown,
    }
    presentation_ref = stable_sha(presentation_identity)
    render_ns = time.perf_counter_ns() - started
    result = {
        **presentation_identity,
        "birth": {**birth_presentation, "certificate_ns": render_ns},
        "publication": {
            "presented": True,
            "share_copy": publication["share_copy"],
            "presentation_ref": presentation_ref,
        },
        "presentation_ref": presentation_ref,
        "render_ns": render_ns,
    }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise CertificatePresentationError("input must be a JSON object")
        result = build_certificate_presentation(payload, home=args.home)
    except (
        BirthError,
        CertificatePresentationError,
        PublicationPresentationError,
        json.JSONDecodeError,
    ) as error:
        print(f"play-certificate: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
