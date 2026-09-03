"""The fan-out runner. Always returns an envelope; never raises.

Extractors run in parallel with their own timeouts and converge once. An
extractor that fails becomes an unknown carrying the error text. If the audit
cannot even load the package, the envelope says ``audit_unavailable`` and the
caller proceeds as if no audit existed.
"""

from __future__ import annotations

import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable, TypeVar

from . import adapters as adapters_mod
from . import bodies as bodies_mod
from . import correlate as correlate_mod
from . import host as host_mod
from . import package as package_mod
from . import steps as steps_mod
from . import store
from .model import SCHEMA, Collected, Finding, Unknown
from .rules import UNKNOWN_EXTRACTOR, RULES

T = TypeVar("T")

WARM_BUDGET_SECONDS = 1.0
COLD_BUDGET_SECONDS = 3.0
_TASK_TIMEOUT_SECONDS = 2.5

try:
    from importlib.metadata import version as _dist_version

    _AUDIT_VERSION = _dist_version("modiqo-play-controller")
except Exception:  # noqa: BLE001
    _AUDIT_VERSION = "unknown"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _guard(name: str, out: Collected, task: Callable[[], T]) -> T | None:
    """Run ``task``; on any failure record an unknown and return None."""
    try:
        return task()
    except BaseException as error:  # noqa: BLE001 - fail-safe by contract
        out.unknown(UNKNOWN_EXTRACTOR, name, f"{type(error).__name__}: {error}")
        return None


def _collect(future: Future[T | None], name: str, out: Collected, deadline: float) -> T | None:
    remaining = max(0.05, deadline - time.monotonic())
    try:
        return future.result(timeout=remaining)
    except FutureTimeout:
        out.unknown(UNKNOWN_EXTRACTOR, name, f"timed out after {_TASK_TIMEOUT_SECONDS:.1f}s")
        return None
    except BaseException as error:  # noqa: BLE001
        out.unknown(UNKNOWN_EXTRACTOR, name, f"{type(error).__name__}: {error}")
        return None


def audit_package(
    root: Path,
    *,
    reference: str | None = None,
    profile: str | None = None,
    read_adapters: bool = True,
    persist: bool = True,
    adapter_reader: Callable[[str], adapters_mod.AdapterInfo] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    out = Collected()
    try:
        package = package_mod.load(root, reference)
    except BaseException as error:  # noqa: BLE001
        return unavailable(reference or str(root), f"{type(error).__name__}: {error}")

    front = package.frontmatter
    if front.error:
        out.unknown(UNKNOWN_EXTRACTOR, "frontmatter", front.error)
    if package.deps_error:
        out.unknown(UNKNOWN_EXTRACTOR, "deps.toml", package.deps_error)
    if package.manifest_error:
        out.unknown(UNKNOWN_EXTRACTOR, "manifest.json", package.manifest_error)

    # Steps are cheap and everything else keys off them, so they run inline.
    step_analysis = _guard("steps", out, lambda: steps_mod.analyze(package)) or steps_mod.StepAnalysis()
    out.extend(step_analysis.collected)

    deadline = time.monotonic() + _TASK_TIMEOUT_SECONDS
    reader = adapter_reader or adapters_mod.read_adapter
    adapter_ids = adapters_mod.adapter_ids(package, step_analysis) if read_adapters else []
    with ThreadPoolExecutor(max_workers=4 + len(adapter_ids)) as pool:
        bodies_future = pool.submit(_guard, "bodies", out, lambda: bodies_mod.analyze(package))
        host_future = pool.submit(_guard, "host", out, lambda: host_mod.resolve(package, profile, step_analysis.commands_run))
        adapter_futures = {
            adapter_id: pool.submit(_guard, f"adapter/{adapter_id}", out, lambda a=adapter_id: reader(a))
            for adapter_id in adapter_ids
        }
        body_analysis = _collect(bodies_future, "bodies", out, deadline) or bodies_mod.BodyAnalysis(available=False)
        host = _collect(host_future, "host", out, deadline)
        infos = {
            adapter_id: info
            for adapter_id, future in adapter_futures.items()
            if (info := _collect(future, f"adapter/{adapter_id}", out, deadline)) is not None
        }

    out.extend(_guard("bodies.correlate", out, lambda: bodies_mod.correlate(package, body_analysis)) or Collected())
    out.extend(_guard("correlate", out, lambda: correlate_mod.correlate(package, step_analysis, body_analysis)) or Collected())
    if infos:
        out.extend(_guard("adapters.correlate", out, lambda: adapters_mod.correlate(package, step_analysis, infos)) or Collected())

    envelope = build_envelope(
        package=package, steps=step_analysis, host=host, collected=out,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        resource_commands=body_analysis.shell_commands | {s.command for s in body_analysis.spawns if s.command},
    )
    if persist:
        stored, error = store.persist(envelope)
        if error:
            envelope["unknowns"].append(Unknown("STORE_FAILED", "store", error).to_dict())
            envelope["summary"]["unknowns"] = len(envelope["unknowns"])
        envelope["history_ref"] = stored
    return envelope


def build_envelope(
    *, package: package_mod.Package, steps: steps_mod.StepAnalysis, host: host_mod.Host | None,
    collected: Collected, elapsed_ms: int, resource_commands: set[str] | None = None,
) -> dict[str, Any]:
    suppressions = package.frontmatter.suppressions
    facts: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for finding in collected.findings:
        key = (finding.id, str(finding.location))
        if key in seen:
            continue
        seen.add(key)
        payload = finding.to_dict()
        if finding.id in suppressions:
            payload["suppressed_reason"] = suppressions[finding.id]
            suppressed.append(payload)
        elif finding.cls == "fact":
            facts.append(payload)
        else:
            judgments.append(payload)
    unknowns = [u.to_dict() for u in collected.unknowns]
    facts.sort(key=lambda f: (f["id"], str(f["location"])))
    judgments.sort(key=lambda f: (f["id"], str(f["location"])))
    cannot_run = _cannot_run(host)
    return {
        "schema": SCHEMA,
        "status": "ok",
        "subject": {
            "reference": package.reference,
            "version": package.version,
            "digest": package.digest,
            "path": str(package.root),
            "audit_version": _AUDIT_VERSION,
            "audited_at": _now(),
            "elapsed_ms": elapsed_ms,
        },
        "host": host.to_dict() if host else None,
        "shape": [shape.to_dict() for shape in steps.shapes],
        "reach": _reach(package, steps, resource_commands or set()),
        "facts": facts,
        "judgments": judgments,
        "unknowns": unknowns,
        "suppressions": suppressed,
        "summary": {
            "open_facts": len(facts),
            "judgments": len(judgments),
            "unknowns": len(unknowns),
            "suppressed": len(suppressed),
            "rules_known": len(RULES),
            "can_run_here": cannot_run is None,
            "cannot_run_reason": cannot_run,
        },
        "history_ref": None,
    }


def _reach(package: package_mod.Package, steps: steps_mod.StepAnalysis, resource_commands: set[str]) -> dict[str, Any]:
    front = package.frontmatter
    services = [endpoint for endpoint in front.endpoints if endpoint.startswith("adapter/")]
    for shape in steps.shapes:
        if shape.endpoint and shape.endpoint not in services:
            services.append(shape.endpoint)
    writes = front.data.get("writes") if isinstance(front.data.get("writes"), list) else front.metadata.get("write_permissions")
    return {
        "commands": sorted(steps.commands_run | resource_commands),
        "services": services,
        "parameters": front.parameter_names,
        "resources": sorted({r for shape in steps.shapes for r in shape.resources}),
        "writes": [str(w) for w in writes] if isinstance(writes, list) else [],
        "unread_bodies": [shape.name for shape in steps.shapes if shape.unread_body],
    }


def _cannot_run(host: host_mod.Host | None) -> str | None:
    if host is None:
        return None
    for need in host.needs:
        if need.status == "missing" or need.status == "profile_absent":
            return f"`{need.name}` is not available on this machine"
        if need.status == "version_low":
            return f"`{need.name}` here is {need.found}; the Play needs {need.declared}"
    return None


def unavailable(reference: str, reason: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "audit_unavailable",
        "reason": reason,
        "subject": {"reference": reference, "audited_at": _now()},
        "facts": [], "judgments": [], "unknowns": [], "suppressions": [], "shape": [],
        "summary": {"open_facts": 0, "judgments": 0, "unknowns": 0, "suppressed": 0, "can_run_here": True, "cannot_run_reason": None},
        "history_ref": None,
    }


def safe_audit(root: Path, **kwargs: Any) -> dict[str, Any]:
    """The one entry every caller should use: never raises, always an envelope."""
    try:
        return audit_package(root, **kwargs)
    except BaseException as error:  # noqa: BLE001
        return unavailable(str(kwargs.get("reference") or root), f"{type(error).__name__}: {error}\n{traceback.format_exc(limit=3)}")


__all__ = ["audit_package", "safe_audit", "unavailable", "build_envelope", "Finding"]
