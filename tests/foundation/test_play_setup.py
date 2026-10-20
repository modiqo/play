from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bin" / "play-setup"
STEP_NAMES = ["routing_policy", "journal_settings", "model_assets"]


class PlaySetupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.play_home = base / "play-home"
        self.state_home = base / "state-home"
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PLAY_ROUTING_USER_PATH", "PLAY_JOURNAL_SETTINGS_PATH"}
        }
        self.environment.update(
            {
                "HOME": str(base),
                "PLAY_HOME": str(self.play_home),
                "PLAY_STATE_HOME": str(self.state_home),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_setup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), *arguments],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def statuses(self, result: subprocess.CompletedProcess[str]) -> list[tuple[str, str]]:
        payload = json.loads(result.stdout)
        self.assertEqual("play.setup/v1", payload["schema"])
        for step in payload["steps"]:
            self.assertEqual({"name", "status", "detail"}, set(step))
        return [(step["name"], step["status"]) for step in payload["steps"]]

    def test_first_run_creates_owner_state_and_rerun_is_current(self) -> None:
        first = self.run_setup("--json")

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(
            [(name, "created") for name in STEP_NAMES], self.statuses(first)
        )
        routing = self.state_home / "routing.yaml"
        self.assertEqual(0o600, routing.stat().st_mode & 0o777)
        self.assertTrue((self.state_home / "journal-settings.json").is_file())
        self.assertTrue((self.play_home / "model-config.yaml").is_file())
        self.assertTrue(
            (self.play_home / "cache" / "model_prices_and_context_window.json").is_file()
        )

        second = self.run_setup("--json")

        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(
            [(name, "current") for name in STEP_NAMES], self.statuses(second)
        )

    def test_rerun_preserves_owner_choices(self) -> None:
        self.state_home.mkdir(parents=True)
        settings = self.state_home / "journal-settings.json"
        settings.write_text(
            json.dumps(
                {
                    "schema": "play.journal-settings/v1",
                    "enabled": True,
                    "exploration": {
                        "enabled": False,
                        "interval_steps": 5,
                        "min_interval_seconds": 120,
                    },
                    "recall": {"enabled": True, "retention_days": 30},
                }
            ),
            encoding="utf-8",
        )
        self.play_home.mkdir(parents=True)
        config = self.play_home / "model-config.yaml"
        config.write_text("schema: play.model-config/v1\nowner: edited\n", encoding="utf-8")

        result = self.run_setup("--json")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(json.loads(settings.read_text())["exploration"]["enabled"])
        self.assertIn("owner: edited", config.read_text())

    def test_invalid_routing_policy_is_an_error_step(self) -> None:
        self.state_home.mkdir(parents=True)
        (self.state_home / "routing.yaml").write_text("routes: nope\n", encoding="utf-8")

        result = self.run_setup("--json")

        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        routing = payload["steps"][0]
        self.assertEqual(("routing_policy", "error"), (routing["name"], routing["status"]))
        self.assertEqual(
            ["created", "created"], [step["status"] for step in payload["steps"][1:]]
        )


if __name__ == "__main__":
    unittest.main()
