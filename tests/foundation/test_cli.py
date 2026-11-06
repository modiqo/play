from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from scripts.lib.play.cli import main


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bin" / "play"


class PlayCliTest(unittest.TestCase):
    def test_help_indexes_recurring_plays_and_developer_tooling(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("RECURRING PLAYS · TULVING", result.stdout)
        self.assertIn("DEVELOPER TOOLING", result.stdout)
        self.assertIn("rote journey next", result.stdout)
        for line in (
            "play recurring probe",
            "play recurring schedule",
            "play schedule",
            "play journey live",
            "play audit <play URI|path>",
        ):
            self.assertIn(line, result.stdout)

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

    def test_audit_delegates_to_play_audit_with_its_arguments(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def executor(path: str, argv: list[str]) -> None:
            calls.append((path, argv))

        self.assertEqual(0, main(["audit", "owner/name@1.0.0", "--author"], executor=executor))
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0].endswith("/play-audit"))
        self.assertEqual(["owner/name@1.0.0", "--author"], calls[0][1][1:])
        self.assertEqual(0, main(["audit"], executor=executor))
        self.assertEqual(["--help"], calls[1][1][1:])

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
