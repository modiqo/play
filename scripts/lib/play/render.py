"""Deterministic rendering primitives shared by Play surfaces."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


def json_text(payload: Any) -> str:
    """Render stable, human-readable UTF-8 JSON for CLI output."""

    return json.dumps(payload, indent=2, ensure_ascii=False)


def compact_json(payload: Mapping[str, Any]) -> str:
    """Render a stable one-line JSON object for exact displayed parameters."""

    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def join_sections(sections: Iterable[str]) -> str:
    """Join non-empty Markdown sections with one blank line."""

    return "\n\n".join(section for section in sections if section)
