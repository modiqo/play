from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.commands import CommandError, run_json


class CommandsTest(unittest.TestCase):
    @patch("play.commands.subprocess.run")
    def test_uses_supported_uppercase_no_hints_environment(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(["rote"], 0, "{}", "")
        run_json(["rote", "registry"], timeout_seconds=2)
        environment = run.call_args.kwargs["env"]
        self.assertEqual("1", environment["ROTE_NO_HINTS"])
        self.assertNotIn("rote_NO_HINTS", environment)

    @patch("play.commands.subprocess.run")
    def test_command_timeout_is_bounded_and_typed(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(["rote", "registry"], 12)
        with self.assertRaisesRegex(CommandError, "timed out after 12s"):
            run_json(["rote", "registry"], timeout_seconds=12)
        self.assertEqual(12, run.call_args.kwargs["timeout"])

    @patch("play.commands.subprocess.run")
    def test_passes_working_directory_to_subprocess(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(["rote"], 0, "{}", "")
        run_json(["rote", "registry"], working_directory=Path("/tmp/workspace"))
        self.assertEqual(Path("/tmp/workspace"), run.call_args.kwargs["cwd"])

    def test_invalid_environment_timeout_fails_before_execution(self) -> None:
        with self.assertRaisesRegex(CommandError, "must be a number"):
            run_json(
                ["rote", "registry"],
                environment={"PLAY_COMMAND_TIMEOUT_SECONDS": "never"},
            )


if __name__ == "__main__":
    unittest.main()
