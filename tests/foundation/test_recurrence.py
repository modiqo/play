from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path

from scripts.lib.play.recurrence import (
    RecurrenceError,
    enable_tulving,
    probe_tulving,
    schedule_play,
)

ROOT = Path(__file__).resolve().parents[2]


def completed(
    command: Sequence[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class RecurrenceTest(unittest.TestCase):
    def test_schedule_command_explains_how_to_install_tulving(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/bin/play-recurring"),
                "schedule",
                "--reference",
                "modiqo/check-registry@1.2.3",
                "--cadence",
                "daily",
                "--why",
                "See what changed",
            ],
            env={**os.environ, "PATH": ""},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual(
            "play-recurring: Tulving is not installed; Play scheduling is unavailable.\n\n"
            "Install and enable Tulving:\n"
            "  brew install modiqo/tap/tulving\n"
            "  tulving init\n\n"
            "Learn more: https://github.com/modiqo/tulving\n",
            result.stderr,
        )

    def test_absent_probe_invokes_nothing(self) -> None:
        calls: list[list[str]] = []

        payload = probe_tulving(
            resolver=lambda _name: None,
            runner=lambda command: calls.append(list(command)) or completed(command),
        )

        self.assertEqual("not_installed", payload["status"])
        self.assertFalse(payload["ready"])
        self.assertEqual([], calls)

    def test_probe_requires_a_healthy_clock(self) -> None:
        def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if command[-1] == "--version":
                return completed(command, stdout="tulving 0.1.0\n")
            return completed(command, stdout="✓ clock    launchd agent\n")

        payload = probe_tulving(
            resolver=lambda name: "/opt/homebrew/bin/tulving" if name == "tulving" else None,
            runner=runner,
        )

        self.assertEqual("ready", payload["status"])
        self.assertTrue(payload["ready"])
        self.assertEqual("tulving 0.1.0", payload["version"])

    def test_enable_installs_with_brew_then_initializes_resolved_binary(self) -> None:
        installed = False
        initialized = False
        calls: list[list[str]] = []

        def resolver(name: str) -> str | None:
            if name == "brew":
                return "/opt/homebrew/bin/brew"
            if name == "tulving" and installed:
                return "/opt/homebrew/bin/tulving"
            return None

        def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            nonlocal installed, initialized
            calls.append(list(command))
            if command[0].endswith("brew"):
                installed = True
            elif command[-1] == "init":
                initialized = True
            elif command[-1] == "--version":
                return completed(command, stdout="tulving 0.1.0\n")
            elif command[-1] == "status":
                clock = "✓ clock" if initialized else "! clock"
                return completed(command, stdout=f"{clock}\n")
            return completed(command)

        payload = enable_tulving(resolver=resolver, runner=runner)

        self.assertTrue(payload["installed"])
        self.assertTrue(payload["initialized"])
        self.assertTrue(payload["ready"])
        self.assertIn(
            ["/opt/homebrew/bin/brew", "install", "modiqo/tap/tulving"],
            calls,
        )
        self.assertIn(["/opt/homebrew/bin/tulving", "init"], calls)

    def test_schedule_invokes_nothing_when_tulving_is_absent(self) -> None:
        calls: list[list[str]] = []

        with self.assertRaises(RecurrenceError) as raised:
            schedule_play(
                reference="modiqo/check-registry@1.2.3",
                cadence="daily",
                why="See what changed",
                resolver=lambda _name: None,
                runner=lambda command, **_kwargs: calls.append(list(command))
                or completed(command),
            )

        self.assertEqual([], calls)
        self.assertEqual(
            "Tulving is not installed; Play scheduling is unavailable.\n\n"
            "Install and enable Tulving:\n"
            "  brew install modiqo/tap/tulving\n"
            "  tulving init\n\n"
            "Learn more: https://github.com/modiqo/tulving",
            str(raised.exception),
        )

    def test_schedule_pins_reference_parameters_reason_and_expiry(self) -> None:
        submitted: list[dict[str, object]] = []

        def runner(
            command: Sequence[str], *, input: str
        ) -> subprocess.CompletedProcess[str]:
            submitted.append(json.loads(input))
            return completed(command, stdout='{"id":"watch-123","status":"active"}\n')

        payload = schedule_play(
            reference="https://play.modiqo.ai/modiqo/check-registry@1.2.3",
            cadence="every morning",
            why="Notice new Plays",
            parameters={"org": "modiqo", "limit": 10},
            resolver=lambda name: "/usr/local/bin/tulving" if name == "tulving" else None,
            runner=runner,
            probe_runner=lambda command: completed(
                command,
                stdout=(
                    "tulving 0.1.0\n"
                    if command[-1] == "--version"
                    else "✓ clock    launchd agent\n"
                ),
            ),
        )

        self.assertEqual("scheduled", payload["status"])
        spec = submitted.pop()
        self.assertEqual("every morning", spec["cadence"])
        self.assertEqual("Notice new Plays", spec["why"])
        self.assertEqual("30d", spec["for"])
        self.assertEqual(
            [
                "rote",
                "play",
                "run",
                "https://play.modiqo.ai/modiqo/check-registry@1.2.3",
                "limit=10",
                "org=modiqo",
                "--yes",
            ],
            spec["argv"],
        )
        self.assertEqual(
            {
                "harness": "play",
                "ref": "https://play.modiqo.ai/modiqo/check-registry@1.2.3",
            },
            spec["origin"],
        )

    def test_schedule_rejects_an_unversioned_reference_before_invocation(self) -> None:
        calls: list[list[str]] = []

        with self.assertRaisesRegex(RecurrenceError, "exact versioned"):
            schedule_play(
                reference="modiqo/check-registry",
                cadence="daily",
                why="Notice new Plays",
                resolver=lambda _name: "/usr/local/bin/tulving",
                runner=lambda command, **_kwargs: calls.append(list(command))
                or completed(command),
                probe_runner=lambda command: completed(
                    command,
                    stdout=(
                        "tulving 0.1.0\n"
                        if command[-1] == "--version"
                        else "✓ clock    launchd agent\n"
                    ),
                ),
            )

        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
