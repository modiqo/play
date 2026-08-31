from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.lib.play.recurrence import (
    RecurrenceError,
    enable_tulving,
    main,
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


def schedules_response(
    command: Sequence[str], schedules: Sequence[Mapping[str, object]] = ()
) -> subprocess.CompletedProcess[str]:
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": f"{len(schedules)} schedule(s)."}],
            "structuredContent": {"schedules": list(schedules)},
            "isError": False,
        },
    }
    return completed(command, stdout=json.dumps(response) + "\n")


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
            "  curl --proto '=https' --tlsv1.2 -fsSL "
            "https://raw.githubusercontent.com/modiqo/tulving/main/install.sh | sh\n"
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

    def test_probe_reports_tulving_independent_update_cycle(self) -> None:
        def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if command[-1] == "--version":
                return completed(command, stdout="tulving 0.1.2\n")
            if command[-1] == "status":
                return completed(command, stdout="✓ clock    launchd agent\n")
            return completed(
                command,
                stdout=json.dumps(
                    {
                        "installed": "0.1.2",
                        "latest": "0.1.3",
                        "update_available": True,
                    }
                ),
            )

        payload = probe_tulving(
            resolver=lambda name: "/usr/local/bin/tulving" if name == "tulving" else None,
            runner=runner,
            check_update=True,
        )

        self.assertEqual("available", payload["update"]["status"])
        self.assertEqual("0.1.2", payload["update"]["installed"])
        self.assertEqual("0.1.3", payload["update"]["latest"])
        self.assertEqual(
            ["/usr/local/bin/tulving", "update", "--check"],
            payload["update"]["check_command"],
        )

    def test_enable_synchronizes_available_tulving_update_after_consent(self) -> None:
        updated = False
        calls: list[list[str]] = []

        def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            nonlocal updated
            calls.append(list(command))
            if command[-1] == "--version":
                version = "0.1.3" if updated else "0.1.2"
                return completed(command, stdout=f"tulving {version}\n")
            if command[-1] == "status":
                return completed(command, stdout="✓ clock    launchd agent\n")
            if command[-2:] == ["update", "--check"]:
                return completed(
                    command,
                    stdout=json.dumps(
                        {
                            "installed": "0.1.2",
                            "latest": "0.1.3",
                            "update_available": True,
                        }
                    ),
                )
            if command[-1] == "update":
                updated = True
            return completed(command)

        payload = enable_tulving(
            resolver=lambda name: "/usr/local/bin/tulving" if name == "tulving" else None,
            runner=runner,
            synchronize_update=True,
        )

        self.assertTrue(payload["updated"])
        self.assertEqual("tulving 0.1.2", payload["previous_version"])
        self.assertEqual("tulving 0.1.3", payload["version"])
        self.assertIn(["/usr/local/bin/tulving", "update"], calls)

    def test_tulving_update_failure_does_not_disable_a_ready_clock(self) -> None:
        def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if command[-1] == "--version":
                return completed(command, stdout="tulving 0.1.2\n")
            if command[-1] == "status":
                return completed(command, stdout="✓ clock    launchd agent\n")
            if command[-2:] == ["update", "--check"]:
                return completed(
                    command,
                    stdout='{"installed":"0.1.2","latest":"0.1.3","update_available":true}',
                )
            return completed(command, returncode=1, stderr="download failed")

        payload = enable_tulving(
            resolver=lambda name: "/usr/local/bin/tulving" if name == "tulving" else None,
            runner=runner,
            synchronize_update=True,
        )

        self.assertTrue(payload["ready"])
        self.assertFalse(payload["updated"])
        self.assertIn("download failed", payload["update_error"])

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
        self.assertEqual("homebrew", payload["installer"])

    def test_enable_uses_official_installer_without_homebrew(self) -> None:
        installed = False
        initialized = False
        calls: list[list[str]] = []

        def resolver(name: str) -> str | None:
            if name == "curl":
                return "/usr/bin/curl"
            if name == "sh":
                return "/bin/sh"
            if name == "tulving" and installed:
                return "/root/.local/bin/tulving"
            return None

        def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            nonlocal installed, initialized
            calls.append(list(command))
            if command[0] == "/bin/sh":
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
        self.assertEqual("official-script", payload["installer"])
        download = next(command for command in calls if command[0] == "/usr/bin/curl")
        self.assertIn("--proto", download)
        self.assertIn("=https", download)
        self.assertIn(
            "https://raw.githubusercontent.com/modiqo/tulving/main/install.sh",
            download,
        )
        self.assertIn(["/root/.local/bin/tulving", "init"], calls)

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
            "  curl --proto '=https' --tlsv1.2 -fsSL "
            "https://raw.githubusercontent.com/modiqo/tulving/main/install.sh | sh\n"
            "  tulving init\n\n"
            "Learn more: https://github.com/modiqo/tulving",
            str(raised.exception),
        )

    def test_schedule_pins_reference_parameters_reason_and_expiry(self) -> None:
        submitted: list[tuple[list[str], dict[str, object]]] = []

        def runner(
            command: Sequence[str], *, input: str
        ) -> subprocess.CompletedProcess[str]:
            if command[-1] == "mcp":
                return schedules_response(command)
            submitted.append((list(command), json.loads(input)))
            schedule_id = "plan-123" if "--dry-run" in command else "watch-123"
            return completed(
                command,
                stdout=f'{{"id":"{schedule_id}","status":"active"}}\n',
            )

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
        self.assertEqual(2, len(submitted))
        self.assertEqual(
            ["/usr/local/bin/tulving", "add", "-", "--dry-run"],
            submitted[0][0],
        )
        self.assertEqual(
            ["/usr/local/bin/tulving", "add", "-"],
            submitted[1][0],
        )
        self.assertEqual(submitted[0][1], submitted[1][1])
        spec = submitted[1][1]
        self.assertEqual("every morning", spec["cadence"])
        self.assertEqual("Notice new Plays", spec["why"])
        self.assertEqual("30d", spec["for"])
        self.assertEqual(
            [
                "rote",
                "play",
                "run",
                "modiqo/check-registry@1.2.3",
                "limit=10",
                "org=modiqo",
                "--yes",
            ],
            spec["argv"],
        )
        self.assertEqual(
            {
                "harness": "play",
                "ref": "modiqo/check-registry@1.2.3",
            },
            spec["origin"],
        )

    def test_schedule_binds_tulving_predicates_change_detection_and_mortality(self) -> None:
        submitted: list[dict[str, object]] = []

        def runner(
            command: Sequence[str], *, input: str
        ) -> subprocess.CompletedProcess[str]:
            if command[-1] == "mcp":
                return schedules_response(command)
            submitted.append(json.loads(input))
            return completed(command, stdout='{"id":"plan-123","status":"active"}\n')

        payload = schedule_play(
            reference="modiqo/watch-catalog@2.0.0",
            cadence="every 6h",
            why="Notice catalog movement",
            max_runs=40,
            until='.done == true',
            on='.added | length > 0',
            notify=["play", "notify-me"],
            on_change="*",
            key="/name",
            tags=["catalog", "play"],
            session="session-123",
            cwd="/work/catalog",
            dry_run_only=True,
            resolver=lambda name: "/usr/local/bin/tulving" if name == "tulving" else None,
            runner=runner,
            probe_runner=lambda command: completed(
                command,
                stdout=(
                    "tulving 0.1.2\n"
                    if command[-1] == "--version"
                    else "✓ clock    launchd agent\n"
                ),
            ),
        )

        self.assertEqual("planned", payload["status"])
        self.assertEqual(1, len(submitted))
        spec = submitted[0]
        self.assertNotIn("for", spec)
        self.assertEqual(40, spec["max_runs"])
        self.assertEqual('.done == true', spec["until"])
        self.assertEqual('.added | length > 0', spec["on"])
        self.assertEqual(["play", "notify-me"], spec["notify"])
        self.assertEqual("*", spec["on_change"])
        self.assertEqual("/name", spec["key"])
        self.assertEqual(["play", "scheduled-play", "catalog"], spec["tags"])
        self.assertEqual(
            {
                "harness": "play",
                "ref": "modiqo/watch-catalog@2.0.0",
                "session": "session-123",
            },
            spec["origin"],
        )
        self.assertEqual("/work/catalog", spec["cwd"])

    def test_schedule_does_not_commit_when_tulving_rejects_the_dry_run(self) -> None:
        calls: list[list[str]] = []

        def runner(
            command: Sequence[str], *, input: str
        ) -> subprocess.CompletedProcess[str]:
            del input
            calls.append(list(command))
            return completed(command, stderr="bad predicate", returncode=1)

        with self.assertRaisesRegex(RecurrenceError, "rejected the schedule plan"):
            schedule_play(
                reference="modiqo/check-registry@1.2.3",
                cadence="daily",
                why="Notice new Plays",
                resolver=lambda _name: "/usr/local/bin/tulving",
                runner=runner,
                probe_runner=lambda command: completed(
                    command,
                    stdout=(
                        "tulving 0.1.2\n"
                        if command[-1] == "--version"
                        else "✓ clock    launchd agent\n"
                    ),
                ),
            )

        self.assertEqual(
            [["/usr/local/bin/tulving", "add", "-", "--dry-run"]],
            calls,
        )

    def test_schedule_rejects_an_active_duplicate_after_validation(self) -> None:
        calls: list[list[str]] = []
        argv = [
            "rote",
            "play",
            "run",
            "modiqo/check-registry@1.2.3",
            "--yes",
        ]

        def runner(
            command: Sequence[str], *, input: str
        ) -> subprocess.CompletedProcess[str]:
            del input
            calls.append(list(command))
            if command[-1] == "mcp":
                return schedules_response(
                    command,
                    [{"id": "existing-1", "status": "active", "argv": argv}],
                )
            return completed(command, stdout='{"id":"plan-123","status":"active"}\n')

        with self.assertRaisesRegex(RecurrenceError, "existing-1.*duplicate"):
            schedule_play(
                reference="modiqo/check-registry@1.2.3",
                cadence="daily",
                why="Notice new Plays",
                resolver=lambda _name: "/usr/local/bin/tulving",
                runner=runner,
                probe_runner=lambda command: completed(
                    command,
                    stdout=(
                        "tulving 0.1.2\n"
                        if command[-1] == "--version"
                        else "✓ clock    launchd agent\n"
                    ),
                ),
            )

        self.assertEqual(
            [
                ["/usr/local/bin/tulving", "add", "-", "--dry-run"],
                ["/usr/local/bin/tulving", "mcp"],
            ],
            calls,
        )

    def test_facade_maps_tulving_read_lifecycle_clock_and_update_commands(self) -> None:
        cases = [
            (["list", "--all"], ["list", "--all"]),
            (["changed", "--since", "2d"], ["changed", "--since", "2d"]),
            (["digest"], ["digest", "--since", "today"]),
            (
                ["recall", "--since", "6h", "--changed", "--schedule", "abc"],
                ["recall", "--since", "6h", "--changed", "--schedule", "abc"],
            ),
            (["why", "abc"], ["why", "abc"]),
            (["why", "abc", "weekly", "review"], ["why", "abc", "weekly", "review"]),
            (["run", "abc"], ["now", "abc"]),
            (["retire", "abc"], ["stop", "abc"]),
            (["snooze", "abc", "2d"], ["snooze", "abc", "2d"]),
            (["snooze", "--all", "1w"], ["snooze", "--all", "1w"]),
            (["status"], ["status"]),
            (["clock", "on"], ["init"]),
            (["clock", "off"], ["uninit"]),
            (["init"], ["init"]),
            (["uninit"], ["uninit"]),
            (["export", "/tmp/tulving.db"], ["export", "/tmp/tulving.db"]),
            (["update"], ["update", "--check"]),
            (["update", "--apply"], ["update"]),
        ]

        for facade, expected in cases:
            with self.subTest(facade=facade):
                calls: list[list[str]] = []
                output = StringIO()
                with redirect_stdout(output):
                    result = main(
                        facade,
                        resolver=lambda _name: "/usr/local/bin/tulving",
                        runner=lambda command: calls.append(list(command))
                        or completed(command, stdout="ok\n"),
                    )
                self.assertEqual(0, result)
                self.assertEqual([["/usr/local/bin/tulving", *expected]], calls)
                self.assertEqual("ok\n", output.getvalue())

    def test_last_returns_the_latest_completed_envelope_from_the_full_ledger(self) -> None:
        calls: list[list[str]] = []
        output = StringIO()
        envelopes = [
            {"run_id": "run-old", "schedule_id": "abc", "missed": False},
            {"run_id": "run-new", "schedule_id": "abc", "missed": False},
            {"run_id": "missed-newer", "schedule_id": "abc", "missed": True},
        ]

        with redirect_stdout(output):
            result = main(
                ["last", "abc"],
                resolver=lambda _name: "/usr/local/bin/tulving",
                runner=lambda command: calls.append(list(command))
                or completed(
                    command,
                    stdout="".join(json.dumps(item) + "\n" for item in envelopes),
                ),
            )

        self.assertEqual(0, result)
        self.assertEqual(
            [
                [
                    "/usr/local/bin/tulving",
                    "recall",
                    "--since",
                    "1970-01-01T00:00:00Z",
                    "--schedule",
                    "abc",
                ]
            ],
            calls,
        )
        self.assertEqual("run-new", json.loads(output.getvalue())["run_id"])

    def test_last_without_an_id_returns_the_latest_run_across_schedules(self) -> None:
        calls: list[list[str]] = []
        output = StringIO()

        with redirect_stdout(output):
            result = main(
                ["last"],
                resolver=lambda _name: "/usr/local/bin/tulving",
                runner=lambda command: calls.append(list(command))
                or completed(
                    command,
                    stdout=(
                        '{"run_id":"first","missed":false}\n'
                        '{"run_id":"latest","missed":false}\n'
                    ),
                ),
            )

        self.assertEqual(0, result)
        self.assertEqual(
            [
                [
                    "/usr/local/bin/tulving",
                    "recall",
                    "--since",
                    "1970-01-01T00:00:00Z",
                ]
            ],
            calls,
        )
        self.assertEqual("latest", json.loads(output.getvalue())["run_id"])

    def test_last_fails_clearly_when_no_completed_run_exists(self) -> None:
        errors = StringIO()

        with redirect_stderr(errors):
            result = main(
                ["last", "abc"],
                resolver=lambda _name: "/usr/local/bin/tulving",
                runner=lambda command: completed(
                    command,
                    stdout='{"run_id":"missed","missed":true}\n',
                ),
            )

        self.assertEqual(1, result)
        self.assertIn("no completed recurring Play runs", errors.getvalue())
        self.assertIn("schedule abc", errors.getvalue())

    def test_facade_rejects_ambiguous_bulk_lifecycle_requests(self) -> None:
        for arguments, message in (
            (["stop"], "one schedule id or --all"),
            (["stop", "abc", "--all"], "one schedule id or --all"),
            (["snooze", "--all", "abc", "1w"], "one duration"),
        ):
            with self.subTest(arguments=arguments):
                errors = StringIO()
                with redirect_stderr(errors):
                    result = main(
                        arguments,
                        resolver=lambda _name: "/usr/local/bin/tulving",
                    )
                self.assertEqual(1, result)
                self.assertIn(message, errors.getvalue())

    def test_structured_list_uses_tulving_mcp_without_exposing_the_transport(self) -> None:
        calls: list[list[str]] = []
        output = StringIO()
        schedules = [{"id": "abc", "status": "active"}]

        with redirect_stdout(output):
            result = main(
                ["list", "--all", "--json"],
                resolver=lambda _name: "/usr/local/bin/tulving",
                input_runner=lambda command, **_kwargs: calls.append(list(command))
                or schedules_response(command, schedules),
            )

        self.assertEqual(0, result)
        self.assertEqual([["/usr/local/bin/tulving", "mcp"]], calls)
        payload = json.loads(output.getvalue())
        self.assertEqual("play.tulving-schedules/v1", payload["schema"])
        self.assertEqual(schedules, payload["schedules"])

    def test_help_covers_every_public_binding_and_names_internal_boundaries(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/bin/play-recurring"), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for command in (
            "schedule",
            "list",
            "changed",
            "digest",
            "recall",
            "last",
            "why",
            "now",
            "stop",
            "snooze",
            "status",
            "clock",
            "init",
            "uninit",
            "export",
            "update",
        ):
            self.assertIn(command, result.stdout)
        self.assertIn("'every' and 'add' write paths", result.stdout)
        self.assertIn("'tick' and transport-only 'mcp'", result.stdout)

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
