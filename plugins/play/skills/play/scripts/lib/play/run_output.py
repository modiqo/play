"""Validate and render complete Play run output without reducing it to a summary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .render import join_sections


SCHEMA = "play.run-output/v1"
DEFAULT_MAX_INLINE_BYTES = 200_000
FULL_OUTPUT_SOURCES = {
    "rote_human_presentation",
    "rote_json_presentation",
    "structured_responses",
}


class RunOutputError(ValueError):
    """A successful run did not provide a complete, renderable primary result."""


def build_detailed_output(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic Markdown only for a complete detailed run result."""

    reference = _non_empty_string(payload, "reference")
    version = _optional_string(payload, "version")
    output = _mapping(payload, "output")
    if output.get("mode") != "detailed":
        raise RunOutputError("run output mode must be detailed")
    if output.get("detail") != "full":
        raise RunOutputError("run output is summary-only; full detail is required")

    source = _non_empty_string(output, "source")
    if source not in FULL_OUTPUT_SOURCES:
        raise RunOutputError(f"run output source {source!r} cannot prove full detail")
    output_format = _non_empty_string(output, "format")
    if output_format not in {"markdown", "json", "text"}:
        raise RunOutputError("run output format must be markdown, json, or text")
    if "primary" not in output or output["primary"] is None:
        raise RunOutputError("run output requires a primary result")

    manifest = _mapping(output, "manifest")
    response_refs = _string_list(manifest, "response_refs")
    artifact_refs = _string_list(manifest, "artifact_refs")
    effects = _string_list(manifest, "effects")
    upstream_truncated = output.get("truncated")
    if not isinstance(upstream_truncated, bool):
        raise RunOutputError("run output truncated must be boolean")
    full_output_ref = _optional_string(output, "full_output_ref")
    if upstream_truncated and full_output_ref is None:
        raise RunOutputError("truncated run output requires full_output_ref")

    policy = payload.get("output_policy")
    if not isinstance(policy, Mapping):
        raise RunOutputError("output_policy must be an object")
    if policy.get("mode") != "detailed":
        raise RunOutputError("output policy mode must be detailed")
    if policy.get("preferred_presentation") not in {"human", "json"}:
        raise RunOutputError("preferred_presentation must be human or json")
    if policy.get("overflow") != "artifact":
        raise RunOutputError("output policy overflow must be artifact")
    max_inline_bytes = policy.get("max_inline_bytes", DEFAULT_MAX_INLINE_BYTES)
    if (
        not isinstance(max_inline_bytes, int)
        or isinstance(max_inline_bytes, bool)
        or max_inline_bytes < 1
    ):
        raise RunOutputError("max_inline_bytes must be a positive integer")

    primary_markdown = _render_primary(output["primary"], output_format)
    primary_bytes = len(primary_markdown.encode("utf-8"))
    inline_overflow = primary_bytes > max_inline_bytes
    if inline_overflow:
        if full_output_ref is None:
            raise RunOutputError(
                "primary result exceeds max_inline_bytes and has no full_output_ref"
            )
        primary_markdown = _truncate_utf8(primary_markdown, max_inline_bytes).rstrip()
        primary_markdown += (
            "\n\n> Inline display limit reached. The complete result is preserved at "
            f"`{full_output_ref}`."
        )

    exact_reference = reference if version is None or "@" in reference else f"{reference}@{version}"
    details = _render_manifest(
        exact_reference,
        source,
        response_refs,
        artifact_refs,
        effects,
        full_output_ref,
    )
    markdown = join_sections(("# Play result", primary_markdown, details))
    presentation_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA,
        "complete": True,
        "mode": "detailed",
        "detail": "full",
        "source": source,
        "format": output_format,
        "truncated": upstream_truncated or inline_overflow,
        "full_output_ref": full_output_ref,
        "inline_bytes": len(markdown.encode("utf-8")),
        "primary_bytes": primary_bytes,
        "presentation_markdown": markdown,
        "presentation_sha256": presentation_sha256,
        "manifest": {
            "response_refs": response_refs,
            "artifact_refs": artifact_refs,
            "effects": effects,
        },
    }


def _render_primary(primary: Any, output_format: str) -> str:
    if output_format == "markdown":
        if not isinstance(primary, str) or not primary.strip():
            raise RunOutputError("markdown primary result must be a non-empty string")
        return primary.strip()
    if output_format == "text":
        if not isinstance(primary, str) or not primary.strip():
            raise RunOutputError("text primary result must be a non-empty string")
        return _fenced("text", primary.rstrip())
    return _render_json(primary)


def _render_json(primary: Any) -> str:
    if _is_flat_record_sequence(primary):
        records = list(primary)
        if records:
            columns = list(dict.fromkeys(key for record in records for key in record))
            header = "| " + " | ".join(_escape_cell(column) for column in columns) + " |"
            divider = "| " + " | ".join("---" for _ in columns) + " |"
            rows = [
                "| "
                + " | ".join(_escape_cell(_scalar_text(record.get(column))) for column in columns)
                + " |"
                for record in records
            ]
            return "\n".join((header, divider, *rows))
    rendered = json.dumps(primary, indent=2, ensure_ascii=False, sort_keys=True)
    return _fenced("json", rendered)


def _is_flat_record_sequence(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and all(
            isinstance(item, Mapping)
            and all(_is_scalar(field) for field in item.values())
            for item in value
        )
    )


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _escape_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _fenced(language: str, value: str) -> str:
    fence = "```"
    while fence in value:
        fence += "`"
    return f"{fence}{language}\n{value}\n{fence}"


def _render_manifest(
    reference: str,
    source: str,
    response_refs: list[str],
    artifact_refs: list[str],
    effects: list[str],
    full_output_ref: str | None,
) -> str:
    lines = [
        "## Run details",
        "",
        f"- Play: `{reference}`",
        f"- Detailed-output source: `{source}`",
        f"- Responses: {_refs(response_refs)}",
        f"- Artifacts: {_refs(artifact_refs)}",
        f"- Effects: {', '.join(effects) if effects else 'none reported'}",
    ]
    if full_output_ref:
        lines.append(f"- Complete output: `{full_output_ref}`")
    return "\n".join(lines)


def _refs(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise RunOutputError(f"{field} must be an object")
    return value


def _non_empty_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise RunOutputError(f"{field} must be a non-empty string")
    return value


def _optional_string(payload: Mapping[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RunOutputError(f"{field} must be a non-empty string or null")
    return value


def _string_list(payload: Mapping[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise RunOutputError(f"{field} must be a unique string list")
    return value
