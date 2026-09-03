"""Extract the ``@rote-frontmatter`` YAML from a Play's main.ts.

The frontmatter lives inside a JSDoc comment, one ``*`` per line, between
``---`` markers. rote generates it; humans and agents edit it. This module only
reads. It never guesses at malformed YAML: a parse failure is returned as an
error string so the runner can record an unknown instead of a wrong finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

_BLOCK = re.compile(r"@rote-frontmatter[ \t]*\n(.*?)\n[ \t]*\*/", re.S)
_PREFIX = re.compile(r"^[ \t]*\*[ ]?")


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
    """Parse the frontmatter block out of a main.ts source string."""
    match = _BLOCK.search(source)
    if match is None:
        return Frontmatter(body=source, error="no @rote-frontmatter block")
    raw_lines = match.group(1).splitlines()
    stripped = [_PREFIX.sub("", line) for line in raw_lines]
    # The YAML document sits between the first two '---' markers. Authors
    # often append usage notes after the closing marker, inside the comment.
    if stripped and stripped[0].strip() == "---":
        stripped = stripped[1:]
        end = next((i for i, line in enumerate(stripped) if line.strip() == "---"), len(stripped))
        stripped = stripped[:end]
    elif stripped and stripped[-1].strip() == "---":
        stripped = stripped[:-1]
    text = "\n".join(stripped)
    line_offset = source[: match.start(1)].count("\n") + 1
    body = source[match.end() :]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return Frontmatter(text=text, body=body, error=f"frontmatter YAML: {error}", line_offset=line_offset)
    if not isinstance(data, dict):
        return Frontmatter(text=text, body=body, error="frontmatter is not a mapping", line_offset=line_offset)
    return Frontmatter(data=data, text=text, body=body, line_offset=line_offset)
