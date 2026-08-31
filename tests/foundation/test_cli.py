from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from scripts.lib.play.cli import FIELD_GUIDE, main


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bin" / "play"


class PlayCliTest(unittest.TestCase):
    def test_help_is_a_themed_index_of_agent_and_shell_operations(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for heading in (
            "AGENT · DISCOVER AND RUN",
            "EXPLORE & VISUALIZE",
            "RECALL & REFERENCE",
            "RECURRING PLAYS · OPTIONAL TULVING",
            "ROUTING",
            "RECOVERY & DIAGNOSTICS",
        ):
            self.assertIn(heading, result.stdout)
        self.assertIn("$play explore <outcome>", result.stdout)
        self.assertIn("play search <outcome>", result.stdout)
        self.assertIn("play journey live", result.stdout)
        self.assertIn("play-journey view --active", result.stdout)
        self.assertIn("play cheat-sheet", result.stdout)
        self.assertIn("play guide [topic]", result.stdout)
        self.assertIn(FIELD_GUIDE, result.stdout)
        self.assertIn("play recurring probe", result.stdout)
        self.assertIn("play recurring list", result.stdout)
        self.assertIn("play recurring recall", result.stdout)
        self.assertIn("play recurring last", result.stdout)
        self.assertIn("play recurring status", result.stdout)
        self.assertIn("play recurring clock on|off", result.stdout)
        self.assertIn("play recurring update", result.stdout)
        self.assertIn("play schedule", result.stdout)
        self.assertIn("play update", result.stdout)
        for journey_operation in (
            "snapshot",
            "graph",
            "story",
            "scene",
            "view",
            "doctor",
            "refresh",
            "rebuild",
            "worker",
        ):
            self.assertIn(journey_operation, result.stdout)

    def test_version_comes_from_the_release_version_file(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"play {(ROOT / 'VERSION').read_text().strip()}\n", result.stdout)

    def test_journey_live_expands_to_the_active_viewer(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["journey", "live", "--no-open", "--port", "4321"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-journey"), executable)
        self.assertEqual(
            [executable, "view", "--active", "--no-open", "--port", "4321"],
            arguments,
        )

    def test_journal_defaults_to_today(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["journal"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-journal"), executable)
        self.assertEqual([executable, "show", "--day", "today"], arguments)

    def test_two_token_whats_new_alias_runs_the_remembered_digest(self) -> None:
        for command in (["what's", "new"], ["whats", "new"]):
            calls: list[tuple[str, list[str]]] = []

            result = main(
                command,
                executor=lambda executable, arguments: calls.append(
                    (executable, arguments)
                ),
            )

            self.assertEqual(0, result)
            executable, arguments = calls.pop()
            self.assertEqual(str(ROOT / "scripts/bin/play-digest"), executable)
            self.assertEqual(
                [executable, "--remember", "--days", "7"], arguments
            )

    def test_schedule_is_an_alias_for_recurring_schedule(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["schedule", "--reference", "modiqo/check@1.2.3"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-recurring"), executable)
        self.assertEqual(
            [executable, "schedule", "--reference", "modiqo/check@1.2.3"],
            arguments,
        )

    def test_guide_delegates_without_preflight_or_identity_recovery(self) -> None:
        calls: list[tuple[str, list[str]]] = []
        identity_calls = []

        result = main(
            ["guide", "run"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
            identity_recoverer=lambda: identity_calls.append(True) or False,
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-guide"), executable)
        self.assertEqual([executable, "run"], arguments)
        self.assertEqual([], identity_calls)

    def test_search_delegates_to_the_unified_local_and_registry_search(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["search", "incident", "triage", "--json"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
            identity_recoverer=lambda: True,
        )

        self.assertEqual(0, result)
        executable, arguments = calls.pop()
        self.assertEqual(str(ROOT / "scripts/bin/play-search"), executable)
        self.assertEqual([executable, "incident", "triage", "--json"], arguments)

    def test_search_stops_before_discovery_when_identity_recovery_fails(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["search", "incident", "triage"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
            identity_recoverer=lambda: False,
        )

        self.assertEqual(1, result)
        self.assertEqual([], calls)

    def test_update_executes_the_bundled_verified_installer(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        result = main(
            ["update", "--harness", "codex"],
            executor=lambda executable, arguments: calls.append(
                (executable, arguments)
            ),
        )

        self.assertEqual(0, result)
        self.assertEqual(
            [
                (
                    "/bin/sh",
                    ["/bin/sh", str(ROOT / "install.sh"), "--harness", "codex"],
                )
            ],
            calls,
        )

    def test_update_help_does_not_download_or_install(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "update", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("play update [installer arguments]", result.stdout)
        self.assertIn("snapshots", result.stdout)

    def test_unknown_command_is_actionable(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "unknown"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("unknown command", result.stderr)
        self.assertIn("play --help", result.stderr)


if __name__ == "__main__":
    unittest.main()
