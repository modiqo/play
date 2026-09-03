"""What this machine, or a named host profile, offers each tool the Play needs."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .model import Need
from .package import Package, Tool

# Interpreters and version-stable tools whose `--version` is safe to probe.
PROBE_ALLOWLIST = {"python3", "python", "node", "deno", "git", "gh", "bash", "jq", "rg", "uv", "ruby", "perl", "go", "rustc"}
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")

# Named profiles: what a consumer's machine ships before they install anything.
PROFILES: dict[str, dict[str, Any]] = {
    "stock-macos": {
        "label": "stock macOS (command line tools only)",
        "os": "darwin",
        "tools": {
            "python3": "3.9.6", "git": "2.39.5", "sh": "present", "bash": "3.2.57", "zsh": "5.9",
            "find": "present", "grep": "present", "sed": "present", "awk": "present", "curl": "8.7.1",
            "perl": "5.34.1", "ruby": "2.6.10", "xargs": "present", "tar": "present", "zip": "present",
            "open": "present", "pbcopy": "present", "osascript": "present", "shasum": "present",
        },
        "absent": ["timeout", "realpath", "sha256sum", "md5sum", "node", "deno", "jq", "gh", "brew", "rg", "uv", "go"],
    },
    "ubuntu-lts": {
        "label": "Ubuntu 24.04 LTS (default install)",
        "os": "linux",
        "tools": {
            "python3": "3.12.3", "git": "2.43.0", "sh": "present", "bash": "5.2.21", "find": "present",
            "grep": "present", "sed": "present", "awk": "present", "curl": "8.5.0", "perl": "5.38.2",
            "xargs": "present", "tar": "present", "timeout": "present", "realpath": "present",
            "sha256sum": "present", "md5sum": "present", "xdg-open": "present", "apt": "present",
        },
        "absent": ["node", "deno", "jq", "gh", "brew", "rg", "uv", "go", "ruby", "open", "pbcopy", "osascript", "zip"],
    },
}


@dataclass
class Host:
    profile: str  # "live" or a PROFILES key
    label: str
    os: str
    needs: list[Need] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile, "label": self.label, "os": self.os, "needs": [n.to_dict() for n in self.needs]}


def parse_requirement(text: str | None) -> tuple[str, tuple[int, ...]] | None:
    if not text:
        return None
    match = re.match(r"\s*(>=|>|==|=|<=|<|\^|~)?\s*v?(\d+(?:\.\d+){0,2})", text)
    if not match:
        return None
    return (match.group(1) or ">="), _tuple(match.group(2))


def _tuple(text: str) -> tuple[int, ...]:
    parts = [int(p) for p in text.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def satisfies(found: str | None, requirement: str | None) -> bool | None:
    """True/False when both sides are known, None when the version could not be compared."""
    parsed = parse_requirement(requirement)
    if parsed is None:
        return None
    if not found or found == "present":
        return None
    match = _VERSION.search(found)
    if not match:
        return None
    op, floor = parsed
    have = _tuple(match.group(0))
    if op in {">=", "^", "~"}:
        return have >= floor
    if op == ">":
        return have > floor
    if op in {"==", "="}:
        return have[:2] == floor[:2] if op == "=" else have == floor
    if op == "<=":
        return have <= floor
    if op == "<":
        return have < floor
    return None


def _probe_version(command: str, path: str) -> str | None:
    if command not in PROBE_ALLOWLIST:
        return None
    for flag in ("--version", "-V", "version"):
        try:
            completed = subprocess.run([path, flag], capture_output=True, text=True, timeout=2.0, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        text = (completed.stdout or completed.stderr).strip()
        match = _VERSION.search(text)
        if match:
            return match.group(0)
    return None


def _need(tool: Tool, found: str | None, path: str | None, present: bool) -> Need:
    if not present:
        status = "missing"
    else:
        ok = satisfies(found, tool.version_requirement)
        if ok is None:
            status = "version_unverified" if tool.version_requirement else "present"
        else:
            status = "present" if ok else "version_low"
    return Need(name=tool.command, declared=tool.version_requirement, found=found, path=path, status=status)


def live(package: Package, *, commands: set[str] | None = None, probe: bool = True) -> Host:
    """Resolve every declared tool, and every command a step runs, on this machine."""
    host = Host(profile="live", label=platform.platform(terse=True), os=platform.system().lower())
    tools = dict(package.tools)
    for command in sorted(commands or set()):
        tools.setdefault(command, Tool(command=command, required=True, version_requirement=None, install_hint=None))
    # When the entrypoint re-executed under uv, PATH now starts with the Play
    # venv; the consumer's real PATH was saved so we resolve what they have.
    search_path = os.environ.get("PLAY_AUDIT_HOST_PATH") or os.environ.get("PATH")
    for command, tool in sorted(tools.items()):
        path = shutil.which(command, path=search_path)
        found = _probe_version(command, path) if (path and probe) else None
        host.needs.append(_need(tool, found, path, path is not None))
    return host


def profiled(package: Package, name: str, *, commands: set[str] | None = None) -> Host:
    spec = PROFILES[name]
    host = Host(profile=name, label=str(spec["label"]), os=str(spec["os"]))
    tools = dict(package.tools)
    for command in sorted(commands or set()):
        tools.setdefault(command, Tool(command=command, required=True, version_requirement=None, install_hint=None))
    shipped: dict[str, str] = spec["tools"]
    absent: set[str] = set(spec["absent"])
    for command, tool in sorted(tools.items()):
        if command in shipped:
            found = shipped[command]
            host.needs.append(_need(tool, None if found == "present" else found, f"<{name}>", True))
        elif command in absent:
            host.needs.append(Need(name=command, declared=tool.version_requirement, found=None, path=None, status="profile_absent"))
        else:
            host.needs.append(Need(name=command, declared=tool.version_requirement, found=None, path=None, status="version_unverified"))
    return host


def resolve(package: Package, profile: str | None, commands: set[str]) -> Host:
    if profile and profile != "live":
        return profiled(package, profile, commands=commands)
    return live(package, commands=commands, probe=not os.environ.get("PLAY_AUDIT_NO_PROBE"))
