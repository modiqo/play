from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.scheduler import (
    describe_claude_cron,
    describe_harness,
    extract_subcommands,
    probe_harnesses,
)


class SchedulerTest(unittest.TestCase):
    def test_parser_ignores_scheduler_words_in_option_prose(self) -> None:
        help_text = """Commands:\n  exec         Run a task\nOptions:\n  --unsafe     bypass automation policy\n"""
        self.assertEqual(["exec"], extract_subcommands(help_text))
        self.assertEqual("unavailable", describe_harness("codex", "codex", help_text)["status"])

    def test_native_recurring_command_is_reported(self) -> None:
        help_text = """Commands:\n  run          Run once\n  schedule     Manage recurring tasks\n"""
        result = describe_harness("future", "future", help_text)
        self.assertEqual("native", result["status"])
        self.assertEqual(["schedule"], result["commands"])

    def test_claude_native_cron_is_detected_from_supported_version(self) -> None:
        result = describe_claude_cron("claude", "2.1.220 (Claude Code)")
        self.assertEqual("native", result["status"])
        self.assertIn("CronCreate", result["commands"])
        self.assertIsNone(describe_claude_cron("claude", "2.1.71 (Claude Code)"))

    def test_probe_distinguishes_not_installed_from_installed_without_scheduler(self) -> None:
        paths = {"present": "/bin/present"}
        payload = probe_harnesses(
            {"one": "present", "two": "missing"},
            resolver=paths.get,
            runner=lambda command: "Commands:\n  run          Run once\n",
        )
        self.assertEqual("play.scheduler-capabilities/v1", payload["schema"])
        self.assertEqual(
            ["unavailable", "not_installed"],
            [item["status"] for item in payload["harnesses"]],
        )


if __name__ == "__main__":
    unittest.main()
