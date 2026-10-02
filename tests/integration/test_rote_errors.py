from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.lib.play.commands import CommandError, run_rote_json

_LEAKY_VARIABLES = (
    "CLAUDECODE",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "ROTE_OUTPUT_MODE",
)


@unittest.skipUnless(shutil.which("rote"), "rote is not on PATH")
class RoteJsonFailureTest(unittest.TestCase):
    def test_failed_json_command_reports_rote_message_not_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            environment = {
                key: value for key, value in os.environ.items() if key not in _LEAKY_VARIABLES
            }
            environment.update(
                HOME=home,
                ROTE_HOME=os.path.join(home, ".rote"),
                ROTE_NO_AUTO_UPDATE="1",
                ROTE_TELEMETRY_DISABLED="1",
                ROTE_NO_HINTS="1",
            )
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(CommandError) as raised:
                    run_rote_json("play", "info", "acme/missing@development", "--json")

        message = str(raised.exception)
        self.assertIn("Play 'acme/missing@development' not found", message)
        self.assertNotIn('{"schema"', message)


if __name__ == "__main__":
    unittest.main()
