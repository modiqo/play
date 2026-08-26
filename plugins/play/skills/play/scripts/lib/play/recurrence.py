"""Optional Tulving capability, setup, and Play scheduling helpers."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any


CAPABILITY_SCHEMA = "play.tulving-capability/v1"
SCHEDULE_SCHEMA = "play.tulving-schedule/v1"
TULVING_FORMULA = "modiqo/tap/tulving"
TULVING_REPOSITORY = "https://github.com/modiqo/tulving"
DEFAULT_DURATION = "30d"
TULVING_INSTALL_GUIDANCE = (
    "Tulving is not installed; Play scheduling is unavailable.\n\n"
    "Install and enable Tulving:\n"
    f"  brew install {TULVING_FORMULA}\n"
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


def probe_tulving(
    *, resolver: Resolver = shutil.which, runner: Runner = _run
) -> dict[str, Any]:
    """Inspect Tulving without invoking anything when the binary is absent."""

    executable = resolver("tulving")
    if executable is None:
        return {
            "schema": CAPABILITY_SCHEMA,
            "status": "not_installed",
            "available": False,
            "ready": False,
            "executable": None,
            "version": None,
            "clock": "unavailable",
        }
    version_result = runner([executable, "--version"])
    if version_result.returncode != 0:
        return {
            "schema": CAPABILITY_SCHEMA,
            "status": "unhealthy",
            "available": True,
            "ready": False,
            "executable": executable,
            "version": None,
            "clock": "unknown",
            "reason": _detail(version_result),
        }
    version = version_result.stdout.strip() or "unknown"
    status_result = runner([executable, "status"])
    if status_result.returncode != 0:
        return {
            "schema": CAPABILITY_SCHEMA,
            "status": "unhealthy",
            "available": True,
            "ready": False,
            "executable": executable,
            "version": version,
            "clock": "unknown",
            "reason": _detail(status_result),
        }
    status_text = status_result.stdout
    clock_ready = "✓ clock" in status_text
    return {
        "schema": CAPABILITY_SCHEMA,
        "status": "ready" if clock_ready else "needs_init",
        "available": True,
        "ready": clock_ready,
        "executable": executable,
        "version": version,
        "clock": "ready" if clock_ready else "not_initialized",
    }


def enable_tulving(
    *, resolver: Resolver = shutil.which, runner: Runner = _run
) -> dict[str, Any]:
    """Install Tulving with Homebrew when needed, then initialize its clock."""

    before = probe_tulving(resolver=resolver, runner=runner)
    installed = False
    if not before["available"]:
        brew = resolver("brew")
        if brew is None:
            raise RecurrenceError(
                "Tulving is absent and Homebrew is unavailable; recurring Play support was not enabled"
            )
        result = runner([brew, "install", TULVING_FORMULA])
        if result.returncode != 0:
            raise RecurrenceError(f"Homebrew could not install Tulving: {_detail(result)}")
        installed = True
    executable = resolver("tulving")
    if executable is None:
        raise RecurrenceError("Tulving installation completed but no executable is on PATH")
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
    return {
        "schema": CAPABILITY_SCHEMA,
        "status": "ready",
        "available": True,
        "ready": True,
        "installed": installed,
        "initialized": initialized,
        "executable": after["executable"],
        "version": after["version"],
        "clock": after["clock"],
    }


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


def schedule_play(
    *,
    reference: str,
    cadence: str,
    why: str,
    parameters: Mapping[str, object] | None = None,
    duration: str = DEFAULT_DURATION,
    resolver: Resolver = shutil.which,
    runner: InputRunner = _schedule_runner,
    probe_runner: Runner = _run,
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
    if not _EXACT_REFERENCE.fullmatch(reference.strip()):
        raise RecurrenceError("scheduling requires an exact versioned Play reference or URI")
    if not cadence.strip():
        raise RecurrenceError("cadence must not be empty")
    if not why.strip():
        raise RecurrenceError("the schedule needs a reason")
    if not re.fullmatch(r"[1-9][0-9]*[mhdw]", duration.strip().lower()):
        raise RecurrenceError("duration must use m, h, d, or w, such as 30d")
    normalized_parameters = dict(parameters or {})
    invalid = sorted(name for name in normalized_parameters if not _PARAMETER_NAME.fullmatch(name))
    if invalid:
        raise RecurrenceError("invalid Play parameter name(s): " + ", ".join(invalid))
    argv = [
        "rote",
        "play",
        "run",
        reference.strip(),
        *[
            f"{name}={_parameter(value)}"
            for name, value in sorted(normalized_parameters.items())
        ],
        "--yes",
    ]
    spec = {
        "argv": argv,
        "cadence": cadence.strip(),
        "why": why.strip(),
        "for": duration.strip().lower(),
        "tags": ["play", "scheduled-play"],
        "origin": {"harness": "play", "ref": reference.strip()},
    }
    result = runner([executable, "add", "-"], input=json.dumps(spec))
    if result.returncode != 0:
        raise RecurrenceError(f"Tulving could not create the schedule: {_detail(result)}")
    try:
        schedule = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RecurrenceError("Tulving returned a malformed schedule receipt") from error
    return {
        "schema": SCHEDULE_SCHEMA,
        "status": "scheduled",
        "reference": reference.strip(),
        "cadence": cadence.strip(),
        "why": why.strip(),
        "duration": duration.strip().lower(),
        "argv": argv,
        "schedule": schedule,
    }


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe")
    subparsers.add_parser("enable")
    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--reference", required=True)
    schedule.add_argument("--cadence", required=True)
    schedule.add_argument("--why", required=True)
    schedule.add_argument("--for", dest="duration", default=DEFAULT_DURATION)
    schedule.add_argument("--parameter", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            payload = probe_tulving()
        elif args.command == "enable":
            payload = enable_tulving()
        else:
            payload = schedule_play(
                reference=args.reference,
                cadence=args.cadence,
                why=args.why,
                duration=args.duration,
                parameters=_parse_parameters(args.parameter),
            )
    except RecurrenceError as error:
        print(f"play-recurring: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
