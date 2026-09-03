"""Release rehearsal: see the Play as consumers will, and prove the presentation
tells the truth when a step fails, is blocked, or returns a truncated stream.

Author-side only. Three parts, each reported separately and none blocking:

1. the consumer card on every requested host profile;
2. the positive fixtures, through ``rote play lint`` (rote's own runtime checks);
3. the packed negative cases, rendered through the presentation with rote's
   deno and SDK, checked against each step's ``expect.yaml``.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import cases, presentation, render, store
from .host import PROFILES
from .package import Package, load
from .runner import safe_audit

DEFAULT_PROFILES = ("live", "stock-macos", "ubuntu-lts")


@dataclass
class CaseResult:
    step: str
    case: str
    verdict: str  # pass | fail | error | skipped
    detail: str
    human: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "case": self.case, "verdict": self.verdict, "detail": self.detail,
                "summary": self.summary[:200], "human_excerpt": self.human[:300]}


@dataclass
class Rehearsal:
    reference: str
    digest: str
    cards: dict[str, str] = field(default_factory=dict)
    envelopes: dict[str, dict[str, Any]] = field(default_factory=dict)
    lint: dict[str, Any] = field(default_factory=dict)
    cases: list[CaseResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(c.verdict == "fail" for c in self.cases):
            return "presentation misreports a negative case"
        if self.lint.get("ran") and not self.lint.get("runtime_checks_passed", True):
            return "rote lint runtime checks failed"
        if not self.cases:
            return "no negative cases packed"
        return "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "play-rehearsal/1",
            "reference": self.reference,
            "digest": self.digest,
            "verdict": self.verdict,
            "profiles": {name: env.get("summary") for name, env in self.envelopes.items()},
            "lint": self.lint,
            "cases": [c.to_dict() for c in self.cases],
            "notes": self.notes,
        }


def _lint(package: Package) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["rote", "play", "lint", str(package.main_path), "--json"],
            capture_output=True, text=True, check=False, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"ran": False, "reason": f"rote play lint could not run: {error}"}
    text = completed.stdout.strip()
    start = text.find("{")
    try:
        payload = json.loads(text[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        payload = {}
    violations = payload.get("violations") or []
    return {
        "ran": True,
        "exit": completed.returncode,
        "static_checks_passed": payload.get("static_checks_passed"),
        "runtime_checks_passed": payload.get("runtime_checks_passed"),
        "violations": [{"code": v.get("code"), "severity": v.get("severity"), "message": str(v.get("message"))[:160]} for v in violations],
    }


def _check(expect: dict[str, Any], case: str, human: str, summary: str, positive_summary: str) -> tuple[str, str]:
    rules = expect.get(case) or {}
    problems: list[str] = []
    needles = rules.get("human_matches_any") or []
    if needles and not any(re.search(needle, human, re.I) for needle in needles):
        problems.append(f"human output mentions none of {needles}")
    if rules.get("summary_must_differ_from_positive") and summary.strip() and summary.strip() == positive_summary.strip():
        problems.append("summary is identical to the positive run's summary")
    forbidden = rules.get("human_must_not_match") or []
    for needle in forbidden:
        if re.search(needle, human, re.I):
            problems.append(f"human output must not mention {needle!r}")
    if problems:
        return "fail", "; ".join(problems)
    return "pass", "presentation names the degraded result"


def rehearse(root: Path, *, profiles: tuple[str, ...] = DEFAULT_PROFILES, reference: str | None = None,
             run_lint: bool = True, persist: bool = True) -> Rehearsal:
    package = load(root, reference)
    result = Rehearsal(reference=package.reference, digest=package.digest)
    for profile in profiles:
        envelope = safe_audit(root, reference=package.reference, profile=None if profile == "live" else profile,
                              read_adapters=True, persist=False)
        result.envelopes[profile] = envelope
        result.cards[profile] = render.card(envelope)
    for profile in profiles:
        if profile != "live" and profile not in PROFILES:
            result.notes.append(f"unknown profile {profile}")

    offenders = cases.is_reachable_from_steps(package)
    if offenders:
        result.notes.append(f"negative cases are referenced by step argv ({', '.join(offenders)}); they would run under `rote play run`")

    result.lint = _lint(package) if run_lint else {"ran": False, "reason": "lint skipped"}

    reason = presentation.available()
    packed = cases.load_cases(package)
    if reason:
        result.notes.append(f"negative cases not rendered: {reason}")
    elif not packed:
        result.notes.append("no negative cases packed; run `play audit fixtures` first")
    else:
        recorded_path = cases.latest_run_input(str(package.frontmatter.data.get("name") or root.name))
        recorded = None
        if recorded_path is not None:
            try:
                recorded = json.loads(recorded_path.read_text())
            except (OSError, json.JSONDecodeError):
                recorded = None
        base = presentation.base_input(package, recorded)
        positive = presentation.render(package, base, "summary")
        positive_summary = positive.stdout if positive.ok else ""
        if not positive.ok:
            result.notes.append(f"positive rendering failed: {positive.stderr.strip()[:200]}")
        for step, entry in packed.items():
            for case, observation in entry["cases"].items():
                payload = presentation.with_outcome(base, step, observation)
                human = presentation.render(package, payload, "human")
                summary = presentation.render(package, payload, "summary")
                if not human.ok:
                    result.cases.append(CaseResult(step, case, "error", f"presentation crashed: {human.stderr.strip().splitlines()[-1][:160] if human.stderr.strip() else 'no output'}"))
                    continue
                verdict, detail = _check(entry["expect"], case, human.stdout, summary.stdout, positive_summary)
                result.cases.append(CaseResult(step, case, verdict, detail, human.stdout, summary.stdout))
    if persist:
        store.append_history(package.reference, {
            "event": "rehearsal", "digest": package.digest, "verdict": result.verdict,
            "cases_pass": sum(c.verdict == "pass" for c in result.cases),
            "cases_fail": sum(c.verdict == "fail" for c in result.cases),
            "cases_error": sum(c.verdict == "error" for c in result.cases),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    return result


def render_text(result: Rehearsal) -> str:
    lines = [f"{result.reference}  digest {result.digest[:23]}", f"  verdict: {result.verdict}", ""]
    for profile, envelope in result.envelopes.items():
        summary = envelope.get("summary") or {}
        can = "can run" if summary.get("can_run_here") else f"cannot run: {summary.get('cannot_run_reason')}"
        lines.append(f"On {profile:12s} {can}; {summary.get('open_facts', 0)} fact(s), {summary.get('unknowns', 0)} unknown(s)")
    lint = result.lint
    if lint.get("ran"):
        lines += ["", f"rote play lint: static {'pass' if lint.get('static_checks_passed') else 'fail'}, runtime {'pass' if lint.get('runtime_checks_passed') else 'fail'}"]
        for v in lint.get("violations", [])[:8]:
            lines.append(f"  {v['severity']:12s} {v['code']}")
    else:
        lines += ["", f"rote play lint: {lint.get('reason')}"]
    if result.cases:
        lines += ["", "Negative cases"]
        for c in result.cases:
            lines.append(f"  {c.verdict:5s} {c.step}/{c.case}: {c.detail}")
            if c.verdict != "pass" and c.summary.strip():
                lines.append(f"        summary said: {c.summary.strip()[:120]}")
    for note in result.notes:
        lines.append(f"note: {note}")
    if result.cards.get("stock-macos"):
        lines += ["", "Card on a stock Mac", *("  " + line for line in result.cards["stock-macos"].splitlines())]
    return "\n".join(lines)
