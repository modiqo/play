"""Render a Play's presentation against a chosen observation, the way rote lint does.

rote runs a presentation with its bundled deno, an import map that binds
``__ROTE_PRESENTATION_SDK__`` to the installed SDK, three environment
variables, and a read-only sandbox. This module reproduces that invocation so
Play can show an author what their presentation says when a step fails, is
blocked, or returns a truncated stream. It is author-side only: the audit
never calls it at pull or run time.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .package import Package

SDK_IMPORT = "__ROTE_PRESENTATION_SDK__"
ENV_INPUT, ENV_MODE, ENV_MARKER = "ROTE_PRESENTATION_INPUT", "ROTE_PRESENTATION_MODE", "ROTE_PRESENTATION"
MODES = ("human", "summary", "json")
_TIMEOUT_SECONDS = 30.0


def rote_home() -> Path:
    override = os.environ.get("ROTE_HOME")
    return Path(override) if override else Path.home() / ".rote"


def deno_binary() -> Path | None:
    candidate = rote_home() / "bin" / "deno"
    return candidate if candidate.is_file() else None


def sdk_entrypoint() -> Path | None:
    candidate = rote_home() / "lib" / "sdk" / "ts" / "presentation.ts"
    return candidate if candidate.is_file() else None


def available() -> str | None:
    """None when the harness can run; otherwise the reason it cannot."""
    if deno_binary() is None:
        return "rote's deno runtime is not installed (expected under $ROTE_HOME/bin/deno)"
    if sdk_entrypoint() is None:
        return "rote's presentation SDK is not installed (expected under $ROTE_HOME/lib/sdk/ts)"
    return None


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_HARNESS_ERROR = re.compile(r"must be (?:a|an) |unsupported value|is not a valid|Cannot find module|import map", re.I)


@dataclass
class Rendered:
    mode: str
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def error_line(self) -> str:
        """The presentation's own error message, without terminal colour codes."""
        clean = _ANSI.sub("", self.stderr)
        for line in clean.splitlines():
            if "rror" in line and "at " not in line[:6]:
                return line.strip()[:200]
        return clean.strip().splitlines()[-1][:200] if clean.strip() else "no output"

    @property
    def harness_fault(self) -> bool:
        """True when the failure is in the synthetic input or runtime, not the presentation."""
        return self.code == 127 or self.code == 126 or _HARNESS_ERROR.search(self.error_line) is not None


def render(package: Package, input_payload: dict[str, Any], mode: str) -> Rendered:
    reason = available()
    if reason:
        return Rendered(mode, 127, "", reason)
    deno, sdk = deno_binary(), sdk_entrypoint()
    assert deno is not None and sdk is not None
    with tempfile.TemporaryDirectory(prefix="play-rehearse-") as temp:
        work = Path(temp)
        input_path = work / "input.json"
        input_path.write_text(json.dumps(input_payload))
        (work / "import_map.json").write_text(json.dumps({"imports": {SDK_IMPORT: sdk.resolve().as_uri()}}))
        argv = [
            str(deno), "run", "--quiet", "--no-config", "--no-remote", "--no-npm",
            f"--import-map={work / 'import_map.json'}",
            f"--allow-env={ENV_INPUT},{ENV_MODE},{ENV_MARKER}",
            f"--allow-read={work},{sdk.resolve().parent},{package.root}",
            str(package.main_path),
        ]
        env = {**os.environ, ENV_INPUT: str(input_path), ENV_MODE: mode, ENV_MARKER: "1"}
        try:
            completed = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=_TIMEOUT_SECONDS, env=env, cwd=package.root)
        except (OSError, subprocess.SubprocessError) as error:
            return Rendered(mode, 126, "", f"presentation could not be started: {error}")
        return Rendered(mode, completed.returncode, completed.stdout, completed.stderr)


# ── observations ──────────────────────────────────────────────────────────

def stream(text: str, *, truncated: bool = False, total_bytes: int | None = None) -> dict[str, Any]:
    encoded = text.encode()
    return {
        "bytes": total_bytes if total_bytes is not None else len(encoded),
        "text": text,
        "preview_bytes": len(encoded),
        "truncated": truncated,
        "encoding": "utf8",
    }


def completed_body(stdout: str, stderr: str = "", *, exit_code: int = 0, timeout_ms: int = 30000,
                   duration_ms: int = 5, truncated: bool = False) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "process.exec",
        "status": {"spawned": True, "exit": {"kind": "code", "code": exit_code}, "timed_out": False,
                   "duration_ms": duration_ms, "timeout_ms": timeout_ms},
        "stdout": stream(stdout, truncated=truncated, total_bytes=(len(stdout.encode()) + 100_000) if truncated else None),
        "stderr": stream(stderr),
    }


def outcome_completed(body: dict[str, Any], response_id: int = 1) -> dict[str, Any]:
    return {"status": "completed", "output": {"shape": "single", "response_id": response_id, "duration": 5, "body": body}}


def outcome_failed(stderr: str, *, exit_code: int = 1, response_id: int = 1) -> dict[str, Any]:
    first = stderr.strip().splitlines()[0] if stderr.strip() else "process failed"
    return {
        "status": "failed",
        "output": {
            "message": f"@{response_id} process exited with code {exit_code}; stderr: {first}",
            "duration": 5,
            "diagnostic": {"response_id": response_id, "exit": {"kind": "code", "code": exit_code}, "stderr": stderr},
        },
    }


def outcome_blocked(blocked_by: list[str]) -> dict[str, Any]:
    return {"status": "blocked", "output": {"reason": "upstream_failed", "blocked_by": blocked_by}}


def definition_for(step: dict[str, Any]) -> dict[str, Any]:
    kind = str(step.get("type") or "process.exec")
    definition: dict[str, Any] = {"kind": kind}
    if kind == "process.exec":
        definition["argv"] = [str(item) for item in step.get("argv", [])] if isinstance(step.get("argv"), list) else []
        definition["timeout_ms"] = int(step.get("timeout_ms") or 30000)
    if "endpoint" in step:
        definition["endpoint"] = str(step["endpoint"])
    if "method" in step:
        definition["method"] = str(step["method"])
    depends = step.get("depends_on")
    if isinstance(depends, list) and depends:
        definition["depends_on"] = [str(d) for d in depends]
    return definition


def fixture_body(package: Package, step: str) -> dict[str, Any] | None:
    """The declared positive fixture for ``step`` as a completed process body, if shipped."""
    relative = package.frontmatter.presentation_fixtures.get(step)
    if not isinstance(relative, str):
        return None
    fixture_path = package.root / relative
    if not fixture_path.is_file():
        return None
    try:
        import yaml

        spec = yaml.safe_load(fixture_path.read_text())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(spec, dict):
        return None

    def read(key: str) -> str:
        value = spec.get(key)
        if not isinstance(value, str):
            return ""
        path = package.root / value
        return path.read_text(errors="replace") if path.is_file() else ""

    raw_status = spec.get("status")
    status: dict[str, Any] = raw_status if isinstance(raw_status, dict) else {}
    raw_exit = status.get("exit")
    exit_spec: dict[str, Any] = raw_exit if isinstance(raw_exit, dict) else {"kind": "code", "code": 0}
    return completed_body(
        read("stdout"), read("stderr"),
        exit_code=int(exit_spec.get("code", 0)) if exit_spec.get("kind") == "code" else 0,
        timeout_ms=int(status.get("timeout_ms", 30000)), duration_ms=int(status.get("duration_ms", 1)),
    )


def base_input(package: Package, recorded: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """A complete presentation input and where it came from: ``recorded`` (a real
    run), ``fixtures`` (every process step has a declared fixture), ``mixed``
    (some do), or ``synthetic`` (none do; every step completes with empty output)."""
    if recorded is not None:
        return copy.deepcopy(recorded), "recorded"
    front = package.frontmatter
    params = {p["name"]: p.get("default", "") for p in front.parameters if "name" in p}
    steps: dict[str, Any] = {}
    fixture_hits, process_count = 0, 0
    for index, (name, step) in enumerate(front.steps.items(), 1):
        definition = definition_for(step)
        if definition["kind"] == "process.exec":
            process_count += 1
            body = fixture_body(package, name)
            if body is not None:
                fixture_hits += 1
            else:
                body = completed_body("", timeout_ms=definition["timeout_ms"])
            outcome = outcome_completed(body, response_id=index)
        else:
            outcome = {"status": "skipped", "output": {"reason": "not part of this rehearsal"}}
        steps[name] = {"definition": definition, "outcome": outcome}
    quality = "synthetic" if fixture_hits == 0 else ("fixtures" if fixture_hits == process_count else "mixed")
    return {
        "flow": {"name": str(front.data.get("name") or package.root.name), "description": str(front.data.get("description") or "")},
        "run": {"run_id": "rehearsal", "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "total_duration": 0, "status": "succeeded"},
        "params": params,
        "steps": steps,
    }, quality


def with_outcome(payload: dict[str, Any], step: str, outcome: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result["steps"].setdefault(step, {"definition": {"kind": "process.exec", "argv": [], "timeout_ms": 30000}})
    result["steps"][step]["outcome"] = outcome
    if outcome.get("status") == "failed":
        result["run"]["status"] = "failed"
        for name, entry in result["steps"].items():
            depends = entry.get("definition", {}).get("depends_on") or []
            if step in depends:
                entry["outcome"] = outcome_blocked([step])
    return result
