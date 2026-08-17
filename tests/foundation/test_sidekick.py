from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.sidekick import append_ledger_entry, capture_for_settle, record_standby


class StandbyBatonPassTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        base = Path(self._temporary.name)
        self.base = base
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

    def test_capture_starts_rote_trajectory_before_the_baton_pass(self) -> None:
        def initialize(name: str) -> Path:
            path = self.base / name
            path.mkdir()
            return path

        result = record_standby(
            {
                "request": {
                    "original": "list my pricing pages in notion",
                    "intent": "list pricing pages in notion",
                    "requested_outcome": "list pricing pages in notion",
                    "excluded": False,
                },
                "match": {"classification": "none"},
                "capture": {
                    "decision": "capture",
                    "reason": "repeatable report",
                    "task_class": "data-fetch-report",
                },
                "preferences": {},
            },
            workspace_initializer=initialize,
        )
        self.assertTrue(result["standby"]["armed"])
        self.assertEqual("capture", result["capture"]["decision"])
        self.assertTrue(result["capture"]["reference"].startswith("cap_"))
        self.assertTrue(result["capture"]["workspace"].startswith("play-capture-"))
        presentation = result["presentation_markdown"]
        assert presentation is not None
        self.assertIn("started before execution", presentation)
        self.assertIn("through Rote workspace", presentation)
        self.assertIn(result["capture"]["reference"], presentation)

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
                "capture": {
                    "decision": "normal",
                    "reason": "not reusable",
                    "task_class": "unclassified",
                },
                "preferences": {},
            }
        )
        self.assertFalse(result["standby"]["armed"])
        self.assertEqual("normal", result["capture"]["decision"])
        self.assertIsNone(result["presentation_markdown"])

    def test_non_global_preferences_require_an_explicit_scope_key(self) -> None:
        for scope in ("session", "project"):
            with self.subTest(scope=scope):
                with self.assertRaisesRegex(ValueError, "require a scope_key"):
                    append_ledger_entry(
                        statement="keep Play quiet here",
                        task_class="ops-maintenance",
                        policy="silent",
                        scope=scope,
                    )

    def test_capture_can_be_settled_only_once_after_trajectory_verification(self) -> None:
        def initialize(name: str) -> Path:
            path = self.base / name
            path.mkdir()
            return path

        result = record_standby(
            {
                "request": {
                    "original": "deploy and verify",
                    "intent": "deploy and verify",
                    "requested_outcome": "deploy and verify",
                    "excluded": False,
                },
                "match": {"classification": "none"},
                "capture": {
                    "decision": "capture",
                    "reason": "repeatable",
                    "task_class": "build-ship-chore",
                },
                "preferences": {},
            },
            workspace_initializer=initialize,
        )
        reference = result["capture"]["reference"]

        capture = capture_for_settle(
            reference, trajectory_validator=lambda _path: "sha256:trajectory"
        )
        self.assertEqual("verified", capture["status"])
        with self.assertRaisesRegex(ValueError, "already settled"):
            capture_for_settle(
                reference, trajectory_validator=lambda _path: "sha256:trajectory"
            )


if __name__ == "__main__":
    unittest.main()
