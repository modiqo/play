"""Typed envelope pieces for the Play audit.

Everything the audit says is one of three things: a finding (a fact or a
judgment), an unknown (something the audit could not see), or a shape record
(what the Play is). The envelope is plain JSON so it can be persisted, diffed,
and rendered by any surface without importing this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA = "play-audit/1"

FindingClass = Literal["fact", "judgment"]
Scope = Literal["package", "host"]


@dataclass(frozen=True)
class Location:
    """Where a finding points: a file and line, or a frontmatter path."""

    file: str | None = None
    line: int | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    def __str__(self) -> str:
        if self.file is not None and self.line is not None:
            return f"{self.file}:{self.line}"
        return self.file or self.path or "package"


@dataclass(frozen=True)
class Finding:
    id: str
    cls: FindingClass
    scope: Scope
    owner: str
    message: str
    location: Location
    fix: str
    evidence: dict[str, Any] = field(default_factory=dict)
    related_issue: str | None = None
    precision: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "class": self.cls,
            "scope": self.scope,
            "owner": self.owner,
            "message": self.message,
            "location": self.location.to_dict(),
            "fix": self.fix,
            "evidence": self.evidence,
        }
        if self.related_issue:
            payload["related_issue"] = self.related_issue
        if self.precision is not None:
            payload["precision"] = self.precision
        return payload


@dataclass(frozen=True)
class Unknown:
    """Something the audit could not see. Never a finding, never omitted."""

    kind: str
    subject: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepShape:
    name: str
    kind: str
    label: str
    commands: list[str] = field(default_factory=list)
    endpoint: str | None = None
    operation: str | None = None
    fan_out: bool = False
    depends_on: list[str] = field(default_factory=list)
    reads_params: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    unread_body: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Need:
    name: str
    declared: str | None
    found: str | None
    path: str | None
    status: str  # present | missing | version_low | version_unverified | profile_absent

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Collected:
    """Mutable accumulator every extractor appends to; converged once at the end."""

    findings: list[Finding] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def unknown(self, kind: str, subject: str, reason: str) -> None:
        self.unknowns.append(Unknown(kind, subject, reason))

    def extend(self, other: Collected) -> None:
        self.findings.extend(other.findings)
        self.unknowns.extend(other.unknowns)
