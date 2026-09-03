"""Extract the ``@rote-frontmatter`` YAML from a Play's main.ts.

The frontmatter lives inside a JSDoc comment, one ``*`` per line, between
``---`` markers. rote generates it; humans and agents edit it. This module only
reads. It never guesses at malformed YAML: a parse failure is returned as an
error string so the runner can record an unknown instead of a wrong finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

_MARKERS = ("@rote-frontmatter", "@dex-frontmatter")


def _marker_in_jsdoc(source: str, position: int) -> bool:
    """Mirror of rote: the marker's line starts with `*` or `/**`, inside an open `/**` block."""
    line_start = source.rfind("\n", 0, position) + 1
    prefix = source[line_start:position].lstrip()
    if not (prefix.startswith("/**") or prefix.startswith("*")):
        return False
    before = source[:position]
    opened, closed = before.rfind("/**"), before.rfind("*/")
    return opened != -1 and (closed == -1 or opened > closed)


def _fence(line: str) -> bool:
    rest = line.strip()
    if not rest.startswith("*"):
        return False
    return rest[1:] in ("---", " ---")


def _strip_prefix(line: str) -> str:
    trimmed = line.strip()
    if trimmed.startswith("* "):
        return trimmed[2:]
    if trimmed.startswith("*"):
        return trimmed[1:].lstrip()
    return trimmed


@dataclass
class Frontmatter:
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    body: str = ""
    error: str | None = None
    # 1-based line of the frontmatter's first YAML line in main.ts, for locations.
    line_offset: int = 0

    @property
    def metadata(self) -> dict[str, Any]:
        value = self.data.get("metadata")
        return value if isinstance(value, dict) else {}

    @property
    def steps(self) -> dict[str, dict[str, Any]]:
        value = self.data.get("steps")
        if not isinstance(value, dict):
            return {}
        return {str(name): (step if isinstance(step, dict) else {}) for name, step in value.items()}

    @property
    def parameters_top_level(self) -> bool:
        return isinstance(self.data.get("parameters"), list)

    @property
    def parameters(self) -> list[dict[str, Any]]:
        raw = self.data.get("parameters")
        if not isinstance(raw, list):
            raw = self.metadata.get("parameters")
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    @property
    def parameter_names(self) -> list[str]:
        return [str(item["name"]) for item in self.parameters if "name" in item]

    @property
    def execution_model(self) -> str | None:
        value = self.metadata.get("execution_model")
        return str(value) if value is not None else None

    @property
    def endpoints(self) -> list[str]:
        raw = self.data.get("requires_endpoints")
        if raw is None:
            raw = self.metadata.get("requires_endpoints")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    @property
    def adapter_sources(self) -> dict[str, str]:
        raw = self.data.get("adapter_sources")
        if raw is None:
            raw = self.metadata.get("adapter_sources")
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items()}

    @property
    def presentation_fixtures(self) -> dict[str, Any]:
        raw = self.data.get("presentation_fixtures")
        if raw is None:
            raw = self.metadata.get("presentation_fixtures")
        return raw if isinstance(raw, dict) else {}

    @property
    def suppressions(self) -> dict[str, str]:
        """``audit.allow: [{rule, reason}]`` declared by the author."""
        audit = self.data.get("audit")
        if audit is None:
            audit = self.metadata.get("audit")
        if not isinstance(audit, dict):
            return {}
        allow = audit.get("allow")
        if not isinstance(allow, list):
            return {}
        result: dict[str, str] = {}
        for item in allow:
            if isinstance(item, dict) and isinstance(item.get("rule"), str):
                result[item["rule"]] = str(item.get("reason") or "no reason given")
        return result


def extract(source: str) -> Frontmatter:
    """Parse the frontmatter block out of a main.ts source string, the way rote does.

    The first marker that sits inside an open JSDoc block wins. The YAML is the
    text between the first two ``* ---`` fence lines after it, bounded by the
    comment's ``*/``; a fence and the close may share a line (``* --- */``).
    """
    marker = min(
        (index for name in _MARKERS for index in _all_indices(source, name) if _marker_in_jsdoc(source, index)),
        default=-1,
    )
    if marker < 0:
        return Frontmatter(body=source, error="no @rote-frontmatter block")
    close = source.find("*/", marker)
    bound = close if close != -1 else len(source)
    lines = source[marker:bound].splitlines(keepends=True)
    offset = marker
    yaml_start: int | None = None
    yaml_end: int | None = None
    for line in lines:
        if _fence(line):
            if yaml_start is None:
                yaml_start = offset + len(line)
            else:
                yaml_end = offset
                break
        offset += len(line)
    body = source[close + 2 :] if close != -1 else ""
    if yaml_start is None or yaml_end is None:
        return Frontmatter(body=body, error="frontmatter fences not found (expected `* ---` lines before the comment closes)")
    text = "\n".join(_strip_prefix(line) for line in source[yaml_start:yaml_end].splitlines())
    line_offset = source[:yaml_start].count("\n") + 1
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return Frontmatter(text=text, body=body, error=f"frontmatter YAML: {error}", line_offset=line_offset)
    if not isinstance(data, dict):
        return Frontmatter(text=text, body=body, error="frontmatter is not a mapping", line_offset=line_offset)
    return Frontmatter(data=data, text=text, body=body, line_offset=line_offset)


def _all_indices(source: str, needle: str) -> list[int]:
    found: list[int] = []
    start = 0
    while (index := source.find(needle, start)) != -1:
        found.append(index)
        start = index + len(needle)
    return found
