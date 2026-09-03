"""Pack positive fixtures and negative cases into a Play, without making them runnable.

Layout written under the package root::

    resources/presentation-fixtures/<step>/fixture.yaml   rote's fixture, declared in frontmatter, lint runs it
    resources/presentation-fixtures/<step>/stdout.txt|json
    resources/presentation-fixtures/<step>/stderr.txt
    resources/cases/<step>/partial/observation.json       step failed: exit 1, stderr names an unreadable path
    resources/cases/<step>/truncated/observation.json     stdout.truncated true
    resources/cases/<step>/blocked/observation.json       upstream failed
    resources/cases/<step>/expect.yaml                    what the rendered presentation must say

Nothing here is referenced by any step's argv, so ``rote play run`` never
executes it. Positive fixtures are consumed by ``rote play lint``; negative
cases by ``play audit rehearse``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import presentation
from .package import Package

FIXTURES_DIR = "presentation-fixtures"
CASES_DIR = "cases"
NEGATIVE_CASES = ("partial", "truncated", "blocked")

DEFAULT_EXPECT: dict[str, Any] = {
    "schema_version": 1,
    "partial": {
        "human_matches_any": ["partial", "skipped", "could not", "unreadable", "not permitted", "incomplete", "failed", "unavailable"],
        "summary_must_differ_from_positive": True,
    },
    "truncated": {
        "human_matches_any": ["partial", "truncat", "cut", "64", "artifact", "incomplete", "summar"],
        "summary_must_differ_from_positive": True,
    },
    "blocked": {
        "human_matches_any": ["unavailable", "blocked", "did not run", "skipped", "failed", "could not", "upstream"],
        "summary_must_differ_from_positive": True,
    },
}


@dataclass
class Scaffold:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    declared: list[str] = field(default_factory=list)
    frontmatter_changed: bool = False


def latest_run_input(play_name: str) -> Path | None:
    """The newest presentation input.json recorded for this Play's workspace."""
    root = presentation.rote_home() / "workspaces"
    if not root.is_dir():
        return None
    candidates = [p for p in root.glob(f"dag-{play_name}-*/.rote/presentation/*/input.json") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


_CHANGES = {"created", "modified", "unchanged", "deleted", "missing"}


def _declared_files(step: dict[str, Any], recorded_files: Any) -> list[dict[str, Any]]:
    """rote requires one fixture entry per file the step declares (stdin file and
    every capture.files item), keyed by the declared label and path string."""
    observed: dict[tuple[str, str], str] = {}
    if isinstance(recorded_files, list):
        for item in recorded_files:
            if isinstance(item, dict) and isinstance(item.get("label"), str):
                observed[(str(item.get("kind") or ""), item["label"])] = str(item.get("change") or "created")
    entries: list[dict[str, Any]] = []
    stdin = step.get("stdin")
    if isinstance(stdin, dict) and isinstance(stdin.get("file"), str):
        change = observed.get(("declared_input", "stdin"), "unchanged")
        entries.append({"kind": "declared_input", "label": "stdin", "path": stdin["file"],
                        "change": change if change in _CHANGES - {"missing", "created"} else "unchanged"})
    capture = step.get("capture")
    files = capture.get("files") if isinstance(capture, dict) else None
    for item in files if isinstance(files, list) else []:
        if isinstance(item, dict) and isinstance(item.get("label"), str) and isinstance(item.get("path"), str):
            change = observed.get(("declared_output", item["label"]), "created")
            entries.append({"kind": "declared_output", "label": item["label"], "path": item["path"],
                            "change": change if change in _CHANGES else "created"})
    return entries


def _fixture_yaml(step_dir: Path, status: dict[str, Any], stdout_name: str, files: list[dict[str, Any]]) -> str:
    rel = f"resources/{FIXTURES_DIR}/{step_dir.name}"
    spec: dict[str, Any] = {
        "schema_version": 1,
        "kind": "process.exec",
        "status": {"exit": status.get("exit", {"kind": "code", "code": 0}),
                   "duration_ms": int(status.get("duration_ms", 1)),
                   "timeout_ms": int(status.get("timeout_ms", 30000))},
        "stdout": f"{rel}/{stdout_name}",
        "stderr": f"{rel}/stderr.txt",
    }
    if files:
        spec["files"] = files
    return yaml.safe_dump(spec, sort_keys=False)


def _cut(text: str) -> str:
    """The first half of a stream, the way a preview cap leaves it; never empty."""
    sample = text if text.strip() else '{"items": ["one", "two", "three", "four"], "note": "cut here'
    return sample[: max(1, len(sample) // 2)]


def _looks_like_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


def scaffold(package: Package, recorded: dict[str, Any] | None, *, write: bool = True) -> Scaffold:
    """Write fixtures from a recorded run and negative cases for every process step."""
    result = Scaffold()
    front = package.frontmatter
    steps_recorded = (recorded or {}).get("steps", {}) if recorded else {}
    for name, step in front.steps.items():
        if str(step.get("type") or "") != "process.exec":
            result.skipped.append(f"{name}: not a process step")
            continue
        timeout_ms = int(step.get("timeout_ms") or 30000)
        recorded_step = steps_recorded.get(name, {})
        outcome = recorded_step.get("outcome", {})
        body = outcome.get("output", {}).get("body") if outcome.get("status") in {"completed", "restored"} else None
        if isinstance(body, list):
            body = body[0] if body else None
        fixture_dir = package.root / "resources" / FIXTURES_DIR / name
        if isinstance(body, dict) and isinstance(body.get("stdout"), dict):
            stdout_text = str(body["stdout"].get("text") or "")
            stderr_text = str((body.get("stderr") or {}).get("text") or "")
            status = dict(body.get("status") or {})
            status["timeout_ms"] = timeout_ms  # lint requires the fixture timeout to equal the step's
            stdout_name = "stdout.json" if _looks_like_json(stdout_text) else "stdout.txt"
            if write:
                fixture_dir.mkdir(parents=True, exist_ok=True)
                (fixture_dir / stdout_name).write_text(stdout_text)
                (fixture_dir / "stderr.txt").write_text(stderr_text)
                (fixture_dir / "fixture.yaml").write_text(_fixture_yaml(fixture_dir, status, stdout_name, _declared_files(step, body.get("files"))))
            result.written.append(f"resources/{FIXTURES_DIR}/{name}/fixture.yaml")
            result.declared.append(name)
            positive_stdout = stdout_text
        else:
            result.skipped.append(f"{name}: no completed observation in the recorded run; positive fixture not written")
            positive_stdout = ""
        cases_dir = package.root / "resources" / CASES_DIR / name
        negatives = {
            # rote fails a step whose process exits 1, even when stdout held the answer (modiqo/rote#2177).
            "partial": presentation.outcome_failed("find: /Users/you/Library/Protected: Operation not permitted\n"),
            # rote keeps the first 64 KiB and sets truncated=true; a JSON stream cut mid-way
            # is no longer valid JSON, which is how modiqo/rote#2180 surfaces to a presentation.
            "truncated": presentation.outcome_completed(presentation.completed_body(
                _cut(positive_stdout), timeout_ms=timeout_ms, truncated=True)),
            "blocked": presentation.outcome_blocked([str(d) for d in (step.get("depends_on") or ["upstream"])]),
        }
        if write:
            for case, observation in negatives.items():
                (cases_dir / case).mkdir(parents=True, exist_ok=True)
                (cases_dir / case / "observation.json").write_text(json.dumps(observation, indent=1))
            expect = cases_dir / "expect.yaml"
            if not expect.exists():
                expect.write_text(yaml.safe_dump(DEFAULT_EXPECT, sort_keys=False))
        for case in NEGATIVE_CASES:
            result.written.append(f"resources/{CASES_DIR}/{name}/{case}/observation.json")
    if write and result.declared:
        result.frontmatter_changed = declare_fixtures(package.main_path, result.declared)
    return result


_STEPS_LINE = re.compile(r"^(?P<prefix>[ \t]*\*[ ]?)steps:[ \t]*$", re.M)
_FIXTURES_LINE = re.compile(r"^(?P<prefix>[ \t]*\*[ ]?)presentation_fixtures:[ \t]*$", re.M)


def declare_fixtures(main_path: Path, steps: list[str]) -> bool:
    """Add or extend the top-level ``presentation_fixtures:`` map in the frontmatter."""
    source = main_path.read_text(encoding="utf-8")
    entries = {name: f"resources/{FIXTURES_DIR}/{name}/fixture.yaml" for name in steps}
    block_match = _FIXTURES_LINE.search(source)
    if block_match:
        prefix = block_match.group("prefix")
        insert_at = block_match.end()
        existing = source[insert_at:]
        missing = [name for name in steps if f"{prefix}  {name}:" not in existing]
        if not missing:
            return False
        lines = "".join(f"\n{prefix}  {name}: {entries[name]}" for name in missing)
        main_path.write_text(source[:insert_at] + lines + source[insert_at:], encoding="utf-8")
        return True
    steps_match = _STEPS_LINE.search(source)
    if steps_match is None:
        return False
    prefix = steps_match.group("prefix")
    block = f"{prefix}presentation_fixtures:\n" + "".join(f"{prefix}  {name}: {entries[name]}\n" for name in steps)
    main_path.write_text(source[: steps_match.start()] + block + source[steps_match.start():], encoding="utf-8")
    return True


def load_cases(package: Package) -> dict[str, dict[str, Any]]:
    """{step: {"cases": {case: observation}, "expect": {...}}} for every packed negative case."""
    root = package.root / "resources" / CASES_DIR
    result: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return result
    for step_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        cases: dict[str, Any] = {}
        for case_dir in sorted(p for p in step_dir.iterdir() if p.is_dir()):
            observation = case_dir / "observation.json"
            if observation.is_file():
                try:
                    cases[case_dir.name] = json.loads(observation.read_text())
                except json.JSONDecodeError:
                    continue
        expect: dict[str, Any] = dict(DEFAULT_EXPECT)
        expect_path = step_dir / "expect.yaml"
        if expect_path.is_file():
            try:
                loaded = yaml.safe_load(expect_path.read_text())
                if isinstance(loaded, dict):
                    expect = {**DEFAULT_EXPECT, **loaded}
            except yaml.YAMLError:
                pass
        if cases:
            result[step_dir.name] = {"cases": cases, "expect": expect}
    return result


def is_reachable_from_steps(package: Package) -> list[str]:
    """Any case or fixture path a step argv references would make it executable; name them."""
    offenders: list[str] = []
    for name, step in package.frontmatter.steps.items():
        text = json.dumps(step)
        if f"resources/{CASES_DIR}/" in text or "@resource{cases/" in text:
            offenders.append(name)
    return offenders


def env_flag(name: str) -> bool:
    return bool(os.environ.get(name))
