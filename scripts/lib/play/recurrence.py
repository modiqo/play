"""Play-owned facade for Tulving recurrence, recall, and lifecycle work."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


CAPABILITY_SCHEMA = "play.tulving-capability/v1"
SCHEDULE_SCHEMA = "play.tulving-schedule/v1"
SCHEDULES_SCHEMA = "play.tulving-schedules/v1"
TULVING_FORMULA = "modiqo/tap/tulving"
TULVING_REPOSITORY = "https://github.com/modiqo/tulving"
TULVING_INSTALLER = "https://raw.githubusercontent.com/modiqo/tulving/main/install.sh"
DEFAULT_DURATION = "30d"
TULVING_INSTALL_GUIDANCE = (
    "Tulving is not installed; Play scheduling is unavailable.\n\n"
    "Install and enable Tulving:\n"
    f"  curl --proto '=https' --tlsv1.2 -fsSL {TULVING_INSTALLER} | sh\n"
    "  tulving init\n\n"
    f"Learn more: {TULVING_REPOSITORY}"
)
_EXACT_REFERENCE = re.compile(
    r"^(?:https://play\.modiqo\.ai/)?"
    r"[A-Za-z0-9][A-Za-z0-9_-]*/"
    r"[A-Za-z0-9][A-Za-z0-9_-]*@"
    r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$"
)
_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class RecurrenceError(RuntimeError):
    """Recurring Play support could not proceed safely."""


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
InputRunner = Callable[..., subprocess.CompletedProcess[str]]
Resolver = Callable[[str], str | None]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "unknown command error").strip()


def _probe_tulving_update(executable: str, runner: Runner) -> dict[str, Any]:
    command = [executable, "update", "--check"]
    result = runner(command)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return {
            "status": "check_failed",
            "installed": None,
            "latest": None,
            "update_available": None,
            "detail": output or f"update check exited {result.returncode}",
            "recommended_action": "review",
            "check_command": command,
        }
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {
            "status": "check_failed",
            "installed": None,
            "latest": None,
            "update_available": None,
            "detail": "Tulving returned an invalid update receipt.",
            "recommended_action": "review",
            "check_command": command,
        }
    installed = payload.get("installed") if isinstance(payload, dict) else None
    latest = payload.get("latest") if isinstance(payload, dict) else None
    available = payload.get("update_available") if isinstance(payload, dict) else None
    if (
        not isinstance(installed, str)
        or not installed
        or not isinstance(latest, str)
        or not latest
        or not isinstance(available, bool)
    ):
        return {
            "status": "check_failed",
            "installed": None,
            "latest": None,
            "update_available": None,
            "detail": "Tulving returned an incomplete update receipt.",
            "recommended_action": "review",
            "check_command": command,
        }
    return {
        "status": "available" if available else "current",
        "installed": installed,
        "latest": latest,
        "update_available": available,
        "detail": (
            f"Tulving {latest} is available; {installed} is installed."
            if available
            else f"Tulving {installed} is current."
        ),
        "recommended_action": "update" if available else "keep",
        "check_command": command,
    }


def _resolve_tulving(resolver: Resolver) -> str | None:
    executable = resolver("tulving")
    if executable is not None or resolver is not shutil.which:
        return executable
    install_root = Path(
        os.environ.get("TULVING_INSTALL_DIR", Path.home() / ".local" / "bin")
    ).expanduser()
    candidate = install_root / "tulving"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def probe_tulving(
    *,
    resolver: Resolver = shutil.which,
    runner: Runner = _run,
    check_update: bool = False,
) -> dict[str, Any]:
    """Inspect Tulving without invoking anything when the binary is absent."""

    executable = _resolve_tulving(resolver)
    if executable is None:
        payload: dict[str, Any] = {
            "schema": CAPABILITY_SCHEMA,
            "status": "not_installed",
            "available": False,
            "ready": False,
            "executable": None,
            "version": None,
            "clock": "unavailable",
        }
        if check_update:
            payload["update"] = {
                "status": "not_installed",
                "installed": None,
                "latest": None,
                "update_available": None,
                "detail": "Tulving is not installed.",
                "recommended_action": "install",
                "check_command": None,
            }
        return payload
    version_result = runner([executable, "--version"])
    if version_result.returncode != 0:
        payload = {
            "schema": CAPABILITY_SCHEMA,
            "status": "unhealthy",
            "available": True,
            "ready": False,
            "executable": executable,
            "version": None,
            "clock": "unknown",
            "reason": _detail(version_result),
        }
        if check_update:
            payload["update"] = _probe_tulving_update(executable, runner)
        return payload
    version = version_result.stdout.strip() or "unknown"
    status_result = runner([executable, "status"])
    if status_result.returncode != 0:
        payload = {
            "schema": CAPABILITY_SCHEMA,
            "status": "unhealthy",
            "available": True,
            "ready": False,
            "executable": executable,
            "version": version,
            "clock": "unknown",
            "reason": _detail(status_result),
        }
        if check_update:
            payload["update"] = _probe_tulving_update(executable, runner)
        return payload
    status_text = status_result.stdout
    clock_ready = "✓ clock" in status_text
    payload = {
        "schema": CAPABILITY_SCHEMA,
        "status": "ready" if clock_ready else "needs_init",
        "available": True,
        "ready": clock_ready,
        "executable": executable,
        "version": version,
        "clock": "ready" if clock_ready else "not_initialized",
    }
    if check_update:
        payload["update"] = _probe_tulving_update(executable, runner)
    return payload


def enable_tulving(
    *,
    resolver: Resolver = shutil.which,
    runner: Runner = _run,
    synchronize_update: bool = False,
) -> dict[str, Any]:
    """Install Tulving when needed, optionally update it, then initialize its clock."""

    before = probe_tulving(
        resolver=resolver,
        runner=runner,
        check_update=synchronize_update,
    )
    installed = False
    installer = None
    if not before["available"]:
        brew = resolver("brew")
        if brew is not None:
            result = runner([brew, "install", TULVING_FORMULA])
            if result.returncode != 0:
                raise RecurrenceError(
                    f"Homebrew could not install Tulving: {_detail(result)}"
                )
            installer = "homebrew"
        else:
            curl = resolver("curl")
            shell = resolver("sh")
            if curl is None or shell is None:
                raise RecurrenceError(
                    "Tulving is absent, and its official installer needs curl and sh"
                )
            with tempfile.TemporaryDirectory(prefix="play-tulving-") as temporary:
                script = Path(temporary) / "install.sh"
                download = runner(
                    [
                        curl,
                        "--proto",
                        "=https",
                        "--tlsv1.2",
                        "-fsSL",
                        TULVING_INSTALLER,
                        "-o",
                        str(script),
                    ]
                )
                if download.returncode != 0:
                    raise RecurrenceError(
                        "Tulving's official installer could not be downloaded: "
                        + _detail(download)
                    )
                result = runner([shell, str(script)])
                if result.returncode != 0:
                    raise RecurrenceError(
                        f"Tulving's official installer failed: {_detail(result)}"
                    )
            installer = "official-script"
        installed = True
    executable = _resolve_tulving(resolver)
    if executable is None:
        raise RecurrenceError("Tulving installation completed but no executable is on PATH")
    updated = False
    update_error = None
    update = before.get("update") if isinstance(before, dict) else None
    if (
        synchronize_update
        and before.get("available") is True
        and isinstance(update, dict)
    ):
        if update.get("status") == "available":
            result = runner([executable, "update"])
            if result.returncode == 0:
                updated = True
            else:
                update_error = f"Tulving update failed: {_detail(result)}"
        elif update.get("status") == "check_failed":
            update_error = f"Tulving update check failed: {update.get('detail')}"
    current = probe_tulving(resolver=resolver, runner=runner)
    initialized = False
    if not current["ready"]:
        result = runner([executable, "init"])
        if result.returncode != 0:
            raise RecurrenceError(f"Tulving could not initialize its clock: {_detail(result)}")
        initialized = True
    after = probe_tulving(resolver=resolver, runner=runner)
    if not after["ready"]:
        raise RecurrenceError("Tulving is installed but its clock is not ready")
    payload = {
        "schema": CAPABILITY_SCHEMA,
        "status": "ready",
        "available": True,
        "ready": True,
        "installed": installed,
        "updated": updated,
        "installer": installer,
        "initialized": initialized,
        "executable": after["executable"],
        "version": after["version"],
        "previous_version": before.get("version"),
        "clock": after["clock"],
    }
    if update_error is not None:
        payload["update_error"] = update_error
    return payload


def _parameter(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _schedule_runner(command: Sequence[str], *, input: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        input=input,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _mcp_tool(
    executable: str,
    name: str,
    arguments: Mapping[str, object],
    *,
    runner: InputRunner = _schedule_runner,
) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": dict(arguments)},
    }
    result = runner([executable, "mcp"], input=json.dumps(request) + "\n")
    if result.returncode != 0:
        raise RecurrenceError(f"Tulving's structured {name} view failed: {_detail(result)}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        response = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise RecurrenceError(f"Tulving returned a malformed structured {name} view") from error
    if "error" in response:
        message = response.get("error", {}).get("message", "unknown MCP error")
        raise RecurrenceError(f"Tulving's structured {name} view failed: {message}")
    payload = response.get("result", {})
    if payload.get("isError"):
        content = payload.get("content", [])
        message = content[0].get("text") if content else "unknown tool error"
        raise RecurrenceError(f"Tulving's structured {name} view failed: {message}")
    structured = payload.get("structuredContent")
    if not isinstance(structured, dict):
        raise RecurrenceError(f"Tulving returned no structured {name} view")
    return structured


def schedule_play(
    *,
    reference: str,
    cadence: str,
    why: str,
    parameters: Mapping[str, object] | None = None,
    duration: str | None = None,
    max_runs: int | None = None,
    expires_at: str | None = None,
    until: str | None = None,
    on: str | None = None,
    notify: Sequence[str] | None = None,
    on_change: str | None = None,
    key: str | None = None,
    tags: Sequence[str] | None = None,
    session: str | None = None,
    cwd: str | None = None,
    dry_run_only: bool = False,
    resolver: Resolver = shutil.which,
    runner: InputRunner = _schedule_runner,
    probe_runner: Runner = _run,
    inspector: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Schedule one exact Play through an already installed Tulving binary."""

    executable = resolver("tulving")
    if executable is None:
        raise RecurrenceError(TULVING_INSTALL_GUIDANCE)
    capability = probe_tulving(resolver=resolver, runner=probe_runner)
    if not capability["ready"]:
        raise RecurrenceError(
            "Tulving is installed but its clock is not ready; run 'tulving init' first"
        )
    requested_reference = reference.strip()
    if not _EXACT_REFERENCE.fullmatch(requested_reference):
        raise RecurrenceError("scheduling requires an exact versioned Play reference or URI")
    normalized_reference = requested_reference.removeprefix("https://play.modiqo.ai/")
    if not cadence.strip():
        raise RecurrenceError("cadence must not be empty")
    if not why.strip():
        raise RecurrenceError("the schedule needs a reason")
    if max_runs is not None and max_runs < 1:
        raise RecurrenceError("max-runs must be a positive integer")
    if not any((duration, max_runs, expires_at, until)):
        duration = DEFAULT_DURATION
    normalized_duration = duration.strip().lower() if duration else None
    if normalized_duration and not re.fullmatch(
        r"[1-9][0-9]*[mhdw]", normalized_duration
    ):
        raise RecurrenceError("duration must use m, h, d, or w, such as 30d")
    normalized_parameters = dict(parameters or {})
    invalid = sorted(name for name in normalized_parameters if not _PARAMETER_NAME.fullmatch(name))
    if invalid:
        raise RecurrenceError("invalid Play parameter name(s): " + ", ".join(invalid))
    _validate_declared_parameters(normalized_reference, normalized_parameters, inspector)
    argv = [
        "rote",
        "play",
        "run",
        normalized_reference,
        *[
            f"{name}={_parameter(value)}"
            for name, value in sorted(normalized_parameters.items())
        ],
        "--yes",
    ]
    origin = {"harness": "play", "ref": normalized_reference}
    if session:
        origin["session"] = session.strip()
    normalized_tags = list(dict.fromkeys(["play", "scheduled-play", *(tags or [])]))
    spec: dict[str, object] = {
        "argv": argv,
        "cadence": cadence.strip(),
        "why": why.strip(),
        "tags": normalized_tags,
        "origin": origin,
    }
    optional_fields: dict[str, object | None] = {
        "for": normalized_duration,
        "max_runs": max_runs,
        "expires_at": expires_at.strip() if expires_at else None,
        "until": until.strip() if until else None,
        "on": on.strip() if on else None,
        "notify": list(notify) if notify else None,
        "on_change": on_change,
        "key": key.strip() if key else None,
        "cwd": cwd.strip() if cwd else None,
    }
    spec.update({name: value for name, value in optional_fields.items() if value is not None})
    encoded_spec = json.dumps(spec, sort_keys=True)
    planned = runner(
        [executable, "add", "-", "--dry-run"],
        input=encoded_spec,
    )
    if planned.returncode != 0:
        raise RecurrenceError(f"Tulving rejected the schedule plan: {_detail(planned)}")
    try:
        normalized_schedule = json.loads(planned.stdout)
    except json.JSONDecodeError as error:
        raise RecurrenceError("Tulving returned a malformed schedule plan") from error
    schedules = _mcp_tool(executable, "schedules", {"all": True}, runner=runner).get(
        "schedules", []
    )
    if not isinstance(schedules, list):
        raise RecurrenceError("Tulving returned malformed schedule inventory")
    duplicate = next(
        (
            schedule
            for schedule in schedules
            if isinstance(schedule, dict)
            and schedule.get("status") == "active"
            and schedule.get("argv") == argv
        ),
        None,
    )
    if duplicate is not None:
        schedule_id = duplicate.get("id", "unknown")
        raise RecurrenceError(
            f"schedule #{schedule_id} already runs this exact Play and parameters; "
            "stop or amend it instead of creating a duplicate"
        )
    if dry_run_only:
        return {
            "schema": SCHEDULE_SCHEMA,
            "status": "planned",
            "reference": normalized_reference,
            "cadence": cadence.strip(),
            "why": why.strip(),
            "duration": normalized_duration,
            "argv": argv,
            "spec": spec,
            "schedule": normalized_schedule,
        }
    result = runner([executable, "add", "-"], input=encoded_spec)
    if result.returncode != 0:
        raise RecurrenceError(f"Tulving could not create the schedule: {_detail(result)}")
    try:
        schedule = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RecurrenceError("Tulving returned a malformed schedule receipt") from error
    return {
        "schema": SCHEDULE_SCHEMA,
        "status": "scheduled",
        "reference": normalized_reference,
        "cadence": cadence.strip(),
        "why": why.strip(),
        "duration": normalized_duration,
        "argv": argv,
        "spec": spec,
        "schedule": schedule,
    }


def forward_tulving(
    arguments: Sequence[str],
    *,
    resolver: Resolver = shutil.which,
    runner: Runner = _run,
) -> subprocess.CompletedProcess[str]:
    """Run one intentional Tulving command without scraping or rewriting its output."""

    executable = resolver("tulving")
    if executable is None:
        raise RecurrenceError(TULVING_INSTALL_GUIDANCE)
    return runner([executable, *arguments])


def _default_inspector(reference: str) -> Mapping[str, Any]:
    from .inspection import inspect_for_run

    return inspect_for_run(reference)


def _validate_declared_parameters(
    reference: str,
    parameters: Mapping[str, object],
    inspector: Callable[[str], Mapping[str, Any]] | None,
) -> None:
    """A schedule runs unattended, so it is checked against the Play's declared
    inputs now: unknown names are rejected and required inputs must be present.
    An inspection that cannot be read leaves the parameters as given."""
    try:
        disclosure = (inspector or _default_inspector)(reference)
    except Exception:  # noqa: BLE001 - the registry may be unreachable; rote validates again at run time
        return
    declared = disclosure.get("parameters")
    if not isinstance(declared, list):
        return
    by_name = {str(p.get("name")): p for p in declared if isinstance(p, Mapping) and p.get("name")}
    unknown = sorted(name for name in parameters if name not in by_name)
    if unknown:
        raise RecurrenceError(
            "unknown Play parameter(s): " + ", ".join(unknown)
            + "; this Play declares: " + (", ".join(sorted(by_name)) or "none")
        )
    missing = [
        f"{name} ({str(spec.get('type') or 'string')}): {str(spec.get('description') or '').strip() or 'no description'}"
        for name, spec in by_name.items()
        if spec.get("required") and name not in parameters and spec.get("default") in (None, "")
    ]
    if missing:
        raise RecurrenceError(
            "the Play needs values for required parameter(s) before it can run unattended; ask for: "
            + "; ".join(missing)
        )


def _parse_parameters(values: Sequence[str]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for value in values:
        name, separator, parameter = value.partition("=")
        if not separator or not name or not parameter:
            raise RecurrenceError("parameters must use name=value")
        if name in parameters:
            raise RecurrenceError(f"duplicate parameter {name!r}")
        parameters[name] = parameter
    return parameters


def _schedule_parser(subparsers: Any) -> None:
    schedule = subparsers.add_parser(
        "schedule",
        aliases=["create"],
        help="validate, then schedule one exact versioned Play",
    )
    schedule.add_argument("--reference", required=True)
    schedule.add_argument("--cadence", required=True)
    schedule.add_argument("--why", required=True)
    schedule.add_argument("--for", dest="duration")
    schedule.add_argument("--max-runs", type=int)
    schedule.add_argument("--expires-at")
    schedule.add_argument("--until")
    schedule.add_argument("--on")
    schedule.add_argument("--notify", nargs="+")
    schedule.add_argument("--on-change", nargs="?", const="*")
    schedule.add_argument("--key")
    schedule.add_argument("--tag", action="append", default=[])
    schedule.add_argument("--session")
    schedule.add_argument("--cwd")
    schedule.add_argument("--parameter", action="append", default=[])
    schedule.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and normalize the schedule without creating it",
    )


def _proxy_arguments(args: argparse.Namespace) -> list[str]:
    command = args.command
    if command in {"list", "ls"}:
        return ["list", *(["--all"] if args.all else [])]
    if command == "changed":
        return ["changed", "--since", args.since]
    if command == "digest":
        return ["digest", "--since", args.since]
    if command == "recall":
        result = ["recall", "--since", args.since]
        if args.changed:
            result.append("--changed")
        if args.failed:
            result.append("--failed")
        if args.schedule_id:
            result.extend(["--schedule", args.schedule_id])
        return result
    if command == "why":
        return ["why", args.id, *args.text]
    if command in {"now", "run"}:
        return ["now", args.id]
    if command in {"stop", "retire"}:
        if bool(args.id) == bool(args.all):
            raise RecurrenceError("stop needs one schedule id or --all")
        return ["stop", *([args.id] if args.id else ["--all"])]
    if command == "snooze":
        if args.all:
            if len(args.targets) != 1:
                raise RecurrenceError("snooze --all needs one duration")
            return ["snooze", "--all", args.targets[0]]
        if len(args.targets) != 2:
            raise RecurrenceError("snooze needs one schedule id and one duration")
        return ["snooze", *args.targets]
    if command == "status":
        return ["status"]
    if command == "clock":
        return {"on": ["init"], "off": ["uninit"], "status": ["status"]}[
            args.action
        ]
    if command == "init":
        return ["init"]
    if command == "uninit":
        return ["uninit"]
    if command == "export":
        return ["export", args.path]
    if command == "update":
        return ["update"] if args.apply else ["update", "--check"]
    raise RecurrenceError(f"unsupported recurring command {command!r}")


def recall_last_run(
    schedule_id: str | None = None,
    *,
    resolver: Resolver = shutil.which,
    runner: Runner = _run,
) -> dict:
    """Return the newest completed envelope retained in Tulving's ledger."""

    executable = resolver("tulving")
    if executable is None:
        raise RecurrenceError(TULVING_INSTALL_GUIDANCE)
    command = [
        executable,
        "recall",
        "--since",
        "1970-01-01T00:00:00Z",
    ]
    if schedule_id:
        command.extend(["--schedule", schedule_id])
    result = runner(command)
    if result.returncode != 0:
        raise RecurrenceError(f"Tulving recall failed: {_detail(result)}")

    latest: dict | None = None
    for line_number, line in enumerate((result.stdout or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError as error:
            raise RecurrenceError(
                f"Tulving recall returned invalid JSON on line {line_number}: {error.msg}"
            ) from error
        if not isinstance(envelope, dict):
            raise RecurrenceError(
                f"Tulving recall returned a non-object envelope on line {line_number}"
            )
        if envelope.get("missed") is not True:
            latest = envelope
    if latest is None:
        scope = f" for schedule {schedule_id}" if schedule_id else ""
        raise RecurrenceError(f"no completed recurring Play runs were found{scope}")
    return latest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Tulving's 'every' and 'add' write paths are bound to 'schedule'. "
            "The OS-only 'tick' and transport-only 'mcp' commands stay internal."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe", help="return machine-readable Tulving readiness")
    subparsers.add_parser("enable", help="install Tulving when absent and start its clock")
    _schedule_parser(subparsers)

    listing = subparsers.add_parser("list", aliases=["ls"], help="list schedules")
    listing.add_argument("--all", action="store_true", help="include retired schedules")
    listing.add_argument("--json", action="store_true", help="return structured schedule data")
    changed = subparsers.add_parser("changed", help="show human-readable movement")
    changed.add_argument("--since", default="24h")
    digest = subparsers.add_parser("digest", help="show a human-readable ledger rollup")
    digest.add_argument("--since", default="today")
    recall = subparsers.add_parser("recall", help="read run envelopes as JSON lines")
    recall.add_argument("--since", default="24h")
    recall.add_argument("--changed", action="store_true")
    recall.add_argument("--failed", action="store_true")
    recall.add_argument("--schedule", dest="schedule_id")
    last = subparsers.add_parser(
        "last", help="show the latest completed run envelope retained in the ledger"
    )
    last.add_argument("id", nargs="?", help="optional schedule id")
    why = subparsers.add_parser("why", help="show or replace a schedule's reason")
    why.add_argument("id")
    why.add_argument("text", nargs="*")
    now = subparsers.add_parser("now", aliases=["run"], help="run one schedule now")
    now.add_argument("id")
    stop = subparsers.add_parser(
        "stop", aliases=["retire"], help="retire schedules without deleting history"
    )
    stop.add_argument("id", nargs="?")
    stop.add_argument("--all", action="store_true")
    snooze = subparsers.add_parser("snooze", help="pause schedules for a duration")
    snooze.add_argument("targets", nargs="+")
    snooze.add_argument("--all", action="store_true")
    subparsers.add_parser("status", help="show clock and recent ledger health")
    clock = subparsers.add_parser("clock", help="start, stop, or inspect Tulving's clock")
    clock.add_argument("action", choices=["on", "off", "status"])
    subparsers.add_parser("init", help="alias for 'clock on'")
    subparsers.add_parser("uninit", help="alias for 'clock off'")
    export = subparsers.add_parser("export", help="back up the ledger safely")
    export.add_argument("path")
    update = subparsers.add_parser("update", help="check for updates; --apply installs one")
    update.add_argument("--apply", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    resolver: Resolver = shutil.which,
    runner: Runner = _run,
    input_runner: InputRunner = _schedule_runner,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            payload = probe_tulving(resolver=resolver, runner=runner)
        elif args.command == "enable":
            payload = enable_tulving(resolver=resolver, runner=runner)
        elif args.command in {"schedule", "create"}:
            payload = schedule_play(
                reference=args.reference,
                cadence=args.cadence,
                why=args.why,
                duration=args.duration,
                max_runs=args.max_runs,
                expires_at=args.expires_at,
                until=args.until,
                on=args.on,
                notify=args.notify,
                on_change=args.on_change,
                key=args.key,
                tags=args.tag,
                session=args.session,
                cwd=args.cwd,
                dry_run_only=args.dry_run,
                parameters=_parse_parameters(args.parameter),
                resolver=resolver,
                runner=input_runner,
                probe_runner=runner,
            )
        elif args.command in {"list", "ls"} and args.json:
            executable = resolver("tulving")
            if executable is None:
                raise RecurrenceError(TULVING_INSTALL_GUIDANCE)
            schedules = _mcp_tool(
                executable,
                "schedules",
                {"all": args.all},
                runner=input_runner,
            ).get("schedules", [])
            payload = {"schema": SCHEDULES_SCHEMA, "schedules": schedules}
        elif args.command == "last":
            payload = recall_last_run(
                args.id,
                resolver=resolver,
                runner=runner,
            )
        else:
            result = forward_tulving(
                _proxy_arguments(args), resolver=resolver, runner=runner
            )
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(
                    result.stderr,
                    end="" if result.stderr.endswith("\n") else "\n",
                    file=sys.stderr,
                )
            return result.returncode
    except RecurrenceError as error:
        print(f"play-recurring: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
