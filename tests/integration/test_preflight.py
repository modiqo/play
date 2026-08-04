from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from scripts.lib.play.preflight import SCHEMA, inspect


class PreflightTest(unittest.TestCase):
    @patch("scripts.lib.play.preflight.shutil.which", return_value=None)
    def test_missing_rote_returns_harness_setup_commands(self, _which: MagicMock) -> None:
        payload = inspect("codex")

        self.assertEqual(SCHEMA, payload["schema"])
        self.assertFalse(payload["ready"])
        self.assertIn("codex plugin marketplace add modiqo/rote-skills", payload["setup_commands"])

    @patch("scripts.lib.play.preflight.run")
    @patch("scripts.lib.play.preflight.shutil.which", return_value="/bin/rote")
    def test_ready_requires_identity_and_play_capability(
        self, _which: MagicMock, run_command: MagicMock
    ) -> None:
        run_command.side_effect = [
            MagicMock(returncode=0, stdout="ok: person@example.com\n", stderr=""),
            MagicMock(returncode=0, stdout="rote play\nUSAGE\n", stderr=""),
        ]

        payload = inspect("claude")

        self.assertTrue(payload["ready"])
        self.assertEqual([], payload["setup_commands"])


if __name__ == "__main__":
    unittest.main()
