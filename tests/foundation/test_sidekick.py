from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.sidekick import record_standby


class StandbyBatonPassTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        base = Path(self._temporary.name)
        self._environment = {
            "PLAY_SIDEKICK_STANDBY_PATH": str(base / "standby.json"),
            "PLAY_SIDEKICK_LEDGER_PATH": str(base / "preferences.json"),
        }
        self._saved = {key: os.environ.get(key) for key in self._environment}
        os.environ.update(self._environment)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temporary.cleanup()

    def test_armed_standby_presents_the_baton_pass(self) -> None:
        result = record_standby(
            {
                "request": {
                    "original": "list my pricing pages in notion",
                    "intent": "list pricing pages in notion",
                    "requested_outcome": "list pricing pages in notion",
                    "excluded": False,
                },
                "match": {"classification": "none"},
                "preferences": {},
            }
        )
        self.assertTrue(result["standby"]["armed"])
        presentation = result["presentation_markdown"]
        assert presentation is not None
        self.assertIn("continuing with the task normally", presentation)
        self.assertIn("rote skill", presentation)
        self.assertIn("$play settle", presentation)

    def test_excluded_exit_stays_silent(self) -> None:
        result = record_standby(
            {
                "request": {
                    "original": "no plays for this",
                    "intent": None,
                    "requested_outcome": None,
                    "excluded": True,
                },
                "match": {},
                "preferences": {},
            }
        )
        self.assertFalse(result["standby"]["armed"])
        self.assertIsNone(result["presentation_markdown"])


if __name__ == "__main__":
    unittest.main()
