"""Read-only capability probing for harness-owned recurring schedulers."""

from __future__ import annotations

import argparse
import re
import shutil
from collections.abc import Callable
from typing import Any

from .commands import CommandError, run_text
from .render import json_text


SCHEMA = "play.scheduler-capabilities/v1"
RECURRING_COMMANDS = frozenset({"schedule", "scheduler", "cron", "automation", "automations"})
DEFAULT_HARNESSES = {"codex": "codex", "claude": "claude", "kimi": "kimi"}
COMMAND_LINE = re.compile(r"^\s{2,}([a-z][a-z0-9-]*)\s{2,}\S")


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
    return {
        "schema": SCHEMA,
        "delivery_contract": "play.digest-delivery/v1",
        "harnesses": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json_text(probe_harnesses()))
    return 0

