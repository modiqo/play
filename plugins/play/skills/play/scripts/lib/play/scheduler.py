"""Read-only capability probing for harness-owned recurring schedulers."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from .commands import CommandError, run_text
from .recurrence import probe_tulving
from .render import json_text


SCHEMA = "play.scheduler-capabilities/v1"
RECURRING_COMMANDS = frozenset({"schedule", "scheduler", "cron", "automation", "automations"})
DEFAULT_HARNESSES = {"codex": "codex", "claude": "claude", "kimi": "kimi"}
COMMAND_LINE = re.compile(r"^\s{2,}([a-z][a-z0-9-]*)\s{2,}\S")
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
CLAUDE_CRON_MINIMUM = (2, 1, 72)


def extract_subcommands(help_text: str) -> list[str]:
    """Extract command names without matching incidental prose in help output."""

    return sorted(
        {
            match.group(1)
            for line in help_text.splitlines()
            if (match := COMMAND_LINE.match(line)) is not None
        }
    )


def describe_harness(name: str, executable: str, help_text: str) -> dict[str, Any]:
    commands = extract_subcommands(help_text)
    recurring = sorted(RECURRING_COMMANDS.intersection(commands))
    if recurring:
        return {
            "harness": name,
            "executable": executable,
            "status": "native",
            "commands": recurring,
            "integration": "invoke play-delivery prepare/release from the native scheduler",
        }
    return {
        "harness": name,
        "executable": executable,
        "status": "unavailable",
        "commands": [],
        "integration": "an authorized external scheduler must invoke the Play delivery contract",
    }


def describe_claude_cron(executable: str, version_text: str) -> dict[str, Any] | None:
    """Recognize Claude's native session scheduler, which is a tool rather than a subcommand."""

    match = VERSION.search(version_text)
    if match is None or tuple(map(int, match.groups())) < CLAUDE_CRON_MINIMUM:
        return None
    return {
        "harness": "claude",
        "executable": executable,
        "status": "native",
        "commands": ["/loop", "CronCreate", "CronList", "CronDelete"],
        "integration": "invoke Play from Claude's session-scoped scheduler",
        "limitations": ["requires an open or resumed session", "recurring tasks expire after 7 days"],
    }


def probe_harnesses(
    harnesses: dict[str, str] | None = None,
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., str] = run_text,
) -> dict[str, Any]:
    results = []
    for name, executable in (harnesses or DEFAULT_HARNESSES).items():
        resolved = resolver(executable)
        if resolved is None:
            results.append(
                {
                    "harness": name,
                    "executable": executable,
                    "status": "not_installed",
                    "commands": [],
                    "integration": "install or expose the harness before probing",
                }
            )
            continue
        try:
            if name == "claude":
                native_cron = describe_claude_cron(resolved, runner([resolved, "--version"]))
                if native_cron is not None:
                    results.append(native_cron)
                    continue
            results.append(describe_harness(name, resolved, runner([resolved, "--help"])))
        except CommandError as error:
            results.append(
                {
                    "harness": name,
                    "executable": resolved,
                    "status": "probe_failed",
                    "commands": [],
                    "reason": str(error),
                    "integration": "resolve the probe failure before scheduling",
                }
            )
    def tulving_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.CompletedProcess(command, 0, runner(command), "")
        except CommandError as error:
            return subprocess.CompletedProcess(command, 1, "", str(error))

    return {
        "schema": SCHEMA,
        "delivery_contract": "play.digest-delivery/v1",
        "harnesses": results,
        "tulving": probe_tulving(resolver=resolver, runner=tulving_runner),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json_text(probe_harnesses()))
    return 0
