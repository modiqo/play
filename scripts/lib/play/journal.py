"""Deterministic exploration pulses projected from a captured Rote workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .journal_settings import journal_enabled, positive_setting
from .journey import SCHEMA as JOURNEY_SCHEMA
from .journey import claim_snapshot, render_snapshot
from .private_store import atomic_write_json, load_json
from .private_store import locked_store
from .render import json_text
from .sidekick import (
    _default_standby_path,
    _load_captures,
    _load_hooks,
    _write_sidekick_store,
)
from .state_home import state_path


SCHEMA = "play.exploration-pulse/v1"
RECALL_SCHEMA = "play.recall-journal/v1"
RECALL_EVENT_SCHEMA = "play.recall-event/v1"
DEFAULT_INTERVAL = 5
MIN_INTERVAL = 2
MAX_INTERVAL = 20
DEFAULT_MIN_INTERVAL_SECONDS = 120
MAX_RECALL_EVENTS = 1024
ANALYTICS_TIMEOUT_SECONDS = 1.5
MAX_TRAJECTORY_ROWS = 5
MAX_DAG_EDGES = 4

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TRACE_HEADER = re.compile(
    r"^Trace:\s+.+?\s+\((?P<responses>\d+) responses, "
    r"(?P<duration>\d+)ms total, (?P<tokens>\d+) tokens\)$"
)
_TRACE_BAR = re.compile(
    r"^\s*@(?P<id>\d+)\s+(?P<method>.+?)\s+[░▒▓█]+\s+"
    r"(?P<duration>\d+)ms\s+\[(?P<tokens>\d+|-)\]\s+"
    r"(?P<status>[✓✗])\s*$"
)
_TRACE_EDGE = re.compile(r"^\s*edge:\s+@(?P<source>\d+)\s+\[(?P<kind>[^]]+)\]")
_TRACE_ERROR = re.compile(
    r"^\s*✗\s+@(?P<id>\d+):\s+(?P<method>.+?)\s+—\s+error"
    r"(?:\s+\(retried as @(?P<retry>\d+)\))?\s*$"
)
_UNSAFE_LABEL = re.compile(r"[^A-Za-z0-9_.:/ -]+")

AnalyticsReader = Callable[[Mapping[str, Any]], dict[str, Any] | None]


def _interval() -> int:
    raw = os.environ.get("PLAY_EXPLORATION_PULSE_INTERVAL")
    try:
        value = (
            int(raw)
            if raw is not None
            else positive_setting("exploration", "interval_steps", DEFAULT_INTERVAL)
        )
    except ValueError:
        value = DEFAULT_INTERVAL
    return max(MIN_INTERVAL, min(value, MAX_INTERVAL))


def _min_interval_seconds() -> int:
    raw = os.environ.get("PLAY_EXPLORATION_PULSE_MIN_SECONDS")
    try:
        return max(
            0,
            int(raw)
            if raw is not None
            else positive_setting(
                "exploration", "min_interval_seconds", DEFAULT_MIN_INTERVAL_SECONDS
            ),
        )
    except ValueError:
        return DEFAULT_MIN_INTERVAL_SECONDS


def _clean(text: str) -> str:
    return _ANSI.sub("", text)


def _label(value: object, *, fallback: str = "operation") -> str:
    """Keep workspace-derived labels inert when rendered through a hook."""

    text = " ".join(str(value or "").split())[:80]
    cleaned = _UNSAFE_LABEL.sub("?", text).strip()
    return cleaned or fallback


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, Mapping):
        return None
    data = value.get("data")
    if isinstance(data, Mapping):
        return dict(data)
    return dict(value)


def parse_trace(text: str) -> dict[str, Any] | None:
    """Parse the stable, metadata-only surfaces rendered by ``rote trace``."""

    header: dict[str, int] | None = None
    bars: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    current_response: int | None = None
    for raw_line in _clean(text).splitlines():
        line = raw_line.rstrip()
        if match := _TRACE_HEADER.match(line):
            header = {
                "responses": int(match.group("responses")),
                "duration_ms": int(match.group("duration")),
                "tokens": int(match.group("tokens")),
            }
            continue
        if match := _TRACE_BAR.match(line):
            current_response = int(match.group("id"))
            bars.append(
                {
                    "response_id": current_response,
                    "method": match.group("method").strip(),
                    "duration_ms": int(match.group("duration")),
                    "tokens": (
                        int(match.group("tokens"))
                        if match.group("tokens") != "-"
                        else None
                    ),
                    "ok": match.group("status") == "✓",
                }
            )
            continue
        if current_response is not None and (match := _TRACE_EDGE.match(line)):
            edges.append(
                {
                    "source": int(match.group("source")),
                    "target": current_response,
                    "kind": match.group("kind"),
                }
            )
            continue
        if match := _TRACE_ERROR.match(line):
            errors.append(
                {
                    "response_id": int(match.group("id")),
                    "method": match.group("method").strip(),
                    "retry_response_id": (
                        int(match.group("retry")) if match.group("retry") else None
                    ),
                }
            )
    if header is None:
        return None
    return {**header, "bars": bars, "edges": edges, "errors": errors}


def _run_rote(capture: Mapping[str, Any], arguments: list[str]) -> str | None:
    executable = shutil.which("rote")
    workspace = capture.get("workspace")
    raw_path = capture.get("workspace_path")
    if executable is None or not isinstance(workspace, str) or not workspace:
        return None
    if not isinstance(raw_path, str):
        return None
    workspace_path = Path(raw_path)
    if not workspace_path.is_dir() or not (workspace_path / ".rote").is_dir():
        return None
    try:
        result = subprocess.run(
            [executable, *arguments],
            cwd=workspace_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=ANALYTICS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def read_workspace_stats(capture: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read the cheap workspace counters used to decide whether a pulse is due."""

    output = _run_rote(capture, ["workspace", "stats", "--json"])
    if output is None:
        return None
    stats = _json_object(output)
    if stats is None or not isinstance(stats.get("commands"), int):
        return None
    return stats


def read_workspace_trace(capture: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read the richer timeline only after the command interval is due."""

    output = _run_rote(capture, ["trace", "--deps"])
    if output is None:
        return None
    return parse_trace(output)


def read_workspace_analytics(capture: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read current Rote analytics without changing the captured workspace."""

    stats = read_workspace_stats(capture)
    trace = read_workspace_trace(capture)
    if stats is None or trace is None:
        return None
    return {"stats": stats, "trace": trace}


def _state(capture: Mapping[str, Any]) -> dict[str, Any]:
    value = capture.get("journal")
    value = value if isinstance(value, Mapping) else {}
    return {
        "last_sequence": int(value.get("last_sequence") or 0),
        "last_response_id": int(value.get("last_response_id") or 0),
        "last_tokens": int(value.get("last_tokens") or 0),
        "last_duration_ms": int(value.get("last_duration_ms") or 0),
        "last_tokens_saved": int(value.get("last_tokens_saved") or 0),
        "pulse_count": int(value.get("pulse_count") or 0),
        "last_pulse_at": (
            value.get("last_pulse_at")
            if isinstance(value.get("last_pulse_at"), str)
            else None
        ),
    }


def _pulse_throttled(state: Mapping[str, Any]) -> bool:
    value = state.get("last_pulse_at")
    if not isinstance(value, str):
        return False
    try:
        previous = datetime.fromisoformat(value)
    except ValueError:
        return False
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - previous).total_seconds() < _min_interval_seconds()


def _tokens_saved(stats: Mapping[str, Any]) -> int:
    savings = stats.get("token_savings")
    if not isinstance(savings, Mapping):
        return 0
    value = savings.get("tokens_saved")
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _project(
    capture: Mapping[str, Any], analytics: Mapping[str, Any], *, interval: int, force: bool
) -> dict[str, Any] | None:
    stats = analytics.get("stats")
    trace = analytics.get("trace")
    if not isinstance(stats, Mapping) or not isinstance(trace, Mapping):
        return None
    commands = stats.get("commands")
    if not isinstance(commands, int) or commands <= 0:
        return None
    state = _state(capture)
    new_commands = commands - state["last_sequence"]
    if new_commands <= 0 or (not force and new_commands < interval):
        return None

    bars = [
        dict(bar)
        for bar in trace.get("bars", [])
        if isinstance(bar, Mapping)
        and isinstance(bar.get("response_id"), int)
        and bar["response_id"] > state["last_response_id"]
    ]
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[int, int, str]] = set()
    for edge in trace.get("edges", []):
        if (
            not isinstance(edge, Mapping)
            or not isinstance(edge.get("source"), int)
            or not isinstance(edge.get("target"), int)
            or edge["target"] <= state["last_response_id"]
        ):
            continue
        key = (int(edge["source"]), int(edge["target"]), str(edge.get("kind") or "dependency"))
        if key in edge_keys:
            continue
        edge_keys.add(key)
        edges.append(dict(edge))
    errors = [
        dict(error)
        for error in trace.get("errors", [])
        if isinstance(error, Mapping)
        and isinstance(error.get("response_id"), int)
        and error["response_id"] > state["last_response_id"]
    ]
    total_tokens = int(trace.get("tokens") or 0)
    total_duration_ms = int(trace.get("duration_ms") or 0)
    tokens_saved = _tokens_saved(stats)
    last_response_id = max(
        [state["last_response_id"], *[int(bar["response_id"]) for bar in bars]]
    )
    return {
        "schema": SCHEMA,
        "intent": str(capture.get("intent") or "Captured exploration"),
        "workspace_steps": commands,
        "new_steps": new_commands,
        "responses": int(trace.get("responses") or 0),
        "new_responses": len(bars),
        "new_successes": sum(bool(bar.get("ok")) for bar in bars),
        "new_errors": sum(not bool(bar.get("ok")) for bar in bars),
        "total_tokens": total_tokens,
        "new_tokens": max(0, total_tokens - state["last_tokens"]),
        "total_duration_ms": total_duration_ms,
        "new_duration_ms": max(0, total_duration_ms - state["last_duration_ms"]),
        "new_operation_duration_ms": sum(int(bar.get("duration_ms") or 0) for bar in bars),
        "tokens_saved": tokens_saved,
        "new_tokens_saved": max(0, tokens_saved - state["last_tokens_saved"]),
        "trajectory": bars[-MAX_TRAJECTORY_ROWS:],
        "edges": edges[-MAX_DAG_EDGES:],
        "errors": errors,
        "cursor": {
            "last_sequence": commands,
            "last_response_id": last_response_id,
            "last_tokens": total_tokens,
            "last_duration_ms": total_duration_ms,
            "last_tokens_saved": tokens_saved,
            "pulse_count": state["pulse_count"] + 1,
            "last_pulse_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def render_pulse(pulse: Mapping[str, Any]) -> str:
    """Render a compact human journal without exposing capture handles or paths."""

    if pulse.get("schema") == JOURNEY_SCHEMA:
        return render_snapshot(pulse)

    successes = int(pulse.get("new_successes") or 0)
    responses = int(pulse.get("new_responses") or 0)
    errors = int(pulse.get("new_errors") or 0)
    status = f"{successes}/{responses} new responses succeeded" if responses else "local reasoning steps recorded"
    if errors:
        status += f" · {errors} error{'s' if errors != 1 else ''} preserved"
    lines = [
        "📍 **Exploration progress**",
        "",
        (
            f"**Progress:** {pulse.get('new_steps', 0)} new workspace steps "
            f"· {pulse.get('workspace_steps', 0)} total · {status}"
        ),
        (
            f"**This pulse:** {pulse.get('new_operation_duration_ms', 0)}ms operation time · "
            f"{pulse.get('new_tokens', 0)} API payload tokens · "
            f"{pulse.get('new_tokens_saved', 0)} tokens avoided through cached queries"
        ),
    ]
    trajectory = pulse.get("trajectory")
    if isinstance(trajectory, list) and trajectory:
        lines.extend(["", "**Trajectory**"])
        for bar in trajectory:
            if not isinstance(bar, Mapping):
                continue
            marker = "✓" if bar.get("ok") else "✗"
            token_value = bar.get("tokens")
            token_text = f" · {token_value} tokens" if isinstance(token_value, int) else ""
            lines.append(
                f"- @{bar.get('response_id')} {_label(bar.get('method'))} {marker} "
                f"· {bar.get('duration_ms')}ms{token_text}"
            )
    edges = pulse.get("edges")
    if isinstance(edges, list) and edges:
        lines.extend(["", "**Evidence DAG**"])
        for edge in edges:
            if isinstance(edge, Mapping):
                lines.append(
                    f"- @{edge.get('source')} → @{edge.get('target')} "
                    f"({edge.get('kind')})"
                )
    errors_value = pulse.get("errors")
    if isinstance(errors_value, list) and errors_value:
        lines.extend(["", "**Friction preserved**"])
        for error in errors_value:
            if not isinstance(error, Mapping):
                continue
            retry = error.get("retry_response_id")
            suffix = f"; recovered at @{retry}" if isinstance(retry, int) else ""
            lines.append(
                f"- @{error.get('response_id')} {_label(error.get('method'))} failed{suffix}"
            )
    lines.extend(
        [
            "",
            "Exploration is still active. Keep steering, ask to try another tool, or use "
            "`direct: <task>` for one turn; return with `continue exploration`.",
        ]
    )
    return "\n".join(lines)


def claim_exploration_pulse(
    *,
    path: Path | None = None,
    reader: AnalyticsReader | None = None,
    force: bool = False,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Claim one due pulse exactly once at a Play-visible response boundary."""

    target = path or _default_standby_path()
    captures = _load_captures(target)
    capture = next(
        (item for item in reversed(captures) if item.get("status") == "active"),
        None,
    )
    if capture is None:
        return None
    if not journal_enabled("exploration"):
        return None
    if reader is None:
        return claim_snapshot(
            capture,
            force=force,
            min_interval_seconds=_min_interval_seconds(),
        )
    if not force and _pulse_throttled(_state(capture)):
        return None
    analytics = reader(capture)
    if analytics is None:
        return None
    pulse = _project(capture, analytics, interval=_interval(), force=force)
    if pulse is None:
        return None

    reference = capture.get("reference")
    with locked_store(target.parent):
        current = _load_captures(target)
        index = next(
            (
                index
                for index, item in enumerate(current)
                if item.get("reference") == reference and item.get("status") == "active"
            ),
            None,
        )
        if index is None:
            return None
        latest_state = _state(current[index])
        cursor = pulse["cursor"]
        if latest_state["last_sequence"] >= int(cursor["last_sequence"]):
            return None
        current[index] = {
            **current[index],
            "journal": {
                **cursor,
                **(
                    {"last_session_id": session_id}
                    if isinstance(session_id, str) and session_id
                    else {}
                ),
            },
        }
        _write_sidekick_store(target, hooks=_load_hooks(target), captures=current)
    return pulse


def _recall_path() -> Path:
    override = os.environ.get("PLAY_RECALL_JOURNAL_PATH")
    return Path(override) if override else state_path("recall-journal.json")


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _load_recall(path: Path) -> dict[str, Any]:
    try:
        value = load_json(path)
    except (OSError, ValueError):
        value = None
    if not isinstance(value, Mapping) or value.get("schema") != RECALL_SCHEMA:
        return {"schema": RECALL_SCHEMA, "events": []}
    events = value.get("events")
    return {
        "schema": RECALL_SCHEMA,
        "events": list(events) if isinstance(events, list) else [],
    }


def _recall_reference(context: Mapping[str, Any]) -> str | None:
    for parent, field in (
        ("inspection", "exact_reference"),
        ("match", "reference"),
        ("publication", "canonical_reference"),
    ):
        value = context.get(parent)
        if not isinstance(value, Mapping):
            continue
        reference = value.get(field)
        if isinstance(reference, str) and reference:
            return reference
    return None


def _recall_kinds(source: str, event: str, target: str) -> tuple[str, ...]:
    if source == "qualify" and event == "exact_play_request" and target == "use_inspect":
        return ("selected",)
    if source == "classify" and event == "full_match" and target == "use_inspect":
        return ("matched",)
    if source == "search_offer" and event == "search_play_selected" and target == "use_inspect":
        return ("matched", "selected")
    if source == "use_offer" and event == "play_run_approved" and target == "use_prepare":
        return ("approved",)
    if source == "use_prepare" and event == "play_run_handoff_ready" and target == "use_run":
        return ("run_started",)
    if source == "use_receipt" and event == "receipt_ready" and target in {
        "receipt",
        "onboarding_result_offer",
    }:
        return ("completed",)
    if source in {
        "use_prepare",
        "use_run",
        "use_authentication_offer",
        "use_authentication_execute",
        "use_verify",
        "use_receipt",
    } and target in {
        "blocked",
        "standby_exit",
    }:
        return ("blocked",)
    return ()


def observe_recall_transition(
    *,
    source: str,
    event: str,
    target: str,
    context: Mapping[str, Any],
    path: Path | None = None,
) -> None:
    """Append privacy-minimal recall lifecycle events from typed transitions."""

    if not journal_enabled("recall"):
        return
    kinds = _recall_kinds(source, event, target)
    if not kinds:
        return
    run_id = context.get("run_id")
    reference = _recall_reference(context)
    if not isinstance(run_id, str) or not run_id or not reference:
        return
    journal_path = path or _recall_path()
    now = _local_now()
    try:
        with locked_store(journal_path.parent):
            store = _load_recall(journal_path)
            events = [item for item in store["events"] if isinstance(item, Mapping)]
            existing_ids = {
                str(item["id"])
                for item in events
                if isinstance(item.get("id"), str)
            }
            for kind in kinds:
                event_id = f"{run_id}:{kind}"
                if event_id in existing_ids:
                    continue
                events.append(
                    {
                        "schema": RECALL_EVENT_SCHEMA,
                        "id": event_id,
                        "kind": kind,
                        "run_id": run_id,
                        "reference": reference,
                        "occurred_at": now.isoformat(timespec="seconds"),
                        "local_day": now.date().isoformat(),
                    }
                )
                existing_ids.add(event_id)
            retention_days = positive_setting("recall", "retention_days", 30)
            cutoff = (now.date() - timedelta(days=retention_days)).isoformat()
            store["events"] = [
                dict(item)
                for item in events
                if isinstance(item.get("local_day"), str)
                and item["local_day"] >= cutoff
            ][-MAX_RECALL_EVENTS:]
            atomic_write_json(journal_path, store)
    except (OSError, ValueError):
        # Journaling is observational and must never interrupt a Play run.
        return


def _resolve_day(value: str | None) -> date:
    today = _local_now().date()
    if value in (None, "today"):
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("day must be today, yesterday, or YYYY-MM-DD") from error


def recall_summary(*, day: str | None = None, path: Path | None = None) -> dict[str, Any]:
    """Project one local day's recalled-Play activity from the durable event log."""

    selected_day = _resolve_day(day)
    journal_path = path or _recall_path()
    store = _load_recall(journal_path)
    events = [
        dict(item)
        for item in store["events"]
        if isinstance(item, Mapping) and item.get("local_day") == selected_day.isoformat()
    ]
    runs: dict[str, dict[str, Any]] = {}
    for item in events:
        run_id = item.get("run_id")
        if not isinstance(run_id, str):
            continue
        run = runs.setdefault(
            run_id,
            {
                "run_id": run_id,
                "reference": item.get("reference"),
                "events": [],
                "last_at": item.get("occurred_at"),
            },
        )
        kind = item.get("kind")
        if isinstance(kind, str) and kind not in run["events"]:
            run["events"].append(kind)
        if str(item.get("occurred_at") or "") > str(run.get("last_at") or ""):
            run["last_at"] = item.get("occurred_at")
    ordered = sorted(runs.values(), key=lambda item: str(item.get("last_at") or ""))
    counts = {
        kind: sum(kind in run["events"] for run in ordered)
        for kind in (
            "matched",
            "selected",
            "approved",
            "run_started",
            "completed",
            "blocked",
        )
    }
    return {
        "schema": "play.recall-summary/v1",
        "day": selected_day.isoformat(),
        "counts": counts,
        "unique_plays": len(
            {
                str(run["reference"])
                for run in ordered
                if isinstance(run.get("reference"), str)
            }
        ),
        "runs": ordered,
    }


def render_recall_summary(summary: Mapping[str, Any]) -> str:
    counts = summary.get("counts")
    counts = counts if isinstance(counts, Mapping) else {}
    day_value = str(summary.get("day") or "today")
    try:
        selected_day = date.fromisoformat(day_value)
    except ValueError:
        selected_day = None
    today = _local_now().date()
    label = "Today" if selected_day == today else "Yesterday" if selected_day == today - timedelta(days=1) else day_value
    runs = summary.get("runs")
    runs = runs if isinstance(runs, list) else []
    lines = [f"📓 **Play recall journal — {label}**", ""]
    if not runs:
        lines.extend(
            [
                "No recalled Play activity has been recorded for this day.",
                "",
                "A journal entry appears when Play finds or selects a saved procedure, then follows it through its run.",
            ]
        )
        return "\n".join(lines)
    lines.append(
        f"**{counts.get('matched', 0)} matched · {counts.get('selected', 0)} selected · "
        f"{counts.get('approved', 0)} approved · "
        f"{counts.get('run_started', 0)} run · {counts.get('completed', 0)} completed · "
        f"{counts.get('blocked', 0)} blocked · {summary.get('unique_plays', 0)} unique Plays**"
    )
    lines.extend(["", "**Journeys**"])
    labels = {
        "matched": "matched",
        "selected": "selected",
        "approved": "approved",
        "run_started": "ran",
        "completed": "completed",
        "blocked": "blocked",
    }
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        kinds = run.get("events")
        kinds = kinds if isinstance(kinds, list) else []
        marker = "✓" if "completed" in kinds else "!" if "blocked" in kinds else "→"
        journey = " → ".join(labels[kind] for kind in labels if kind in kinds)
        lines.append(f"- {marker} `{run.get('reference')}` — {journey}")
    lines.extend(
        [
            "",
            "This journal is assembled from typed Play lifecycle events; prompts and credentials are not stored.",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-journal", description=__doc__)
    parser.add_argument("command", choices=["pulse", "show", "recall"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--day", default="today")
    arguments = parser.parse_args(argv)
    if arguments.command in {"show", "recall"}:
        try:
            summary = recall_summary(day=arguments.day)
        except ValueError as error:
            parser.error(str(error))
        print(json_text(summary) if arguments.json else render_recall_summary(summary))
        return 0
    pulse = claim_exploration_pulse(force=arguments.force)
    if pulse is None:
        return 0
    print(json_text(pulse) if arguments.json else render_pulse(pulse))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
