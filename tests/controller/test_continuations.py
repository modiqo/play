from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.continuations import create, discard, load, save
from play.controller import ControllerRuntime
from play.private_store import PrivateStoreError


class ContinuationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = ControllerRuntime(ROOT)

    def test_short_owner_private_continuation_round_trips(self) -> None:
        session = self.runtime.initial_session(
            run_id="continuation-run",
            task_key="continuation-task",
            request_original="run hello",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "continuations"
            continuation_id = create(session, root=root)

            self.assertEqual(24, len(continuation_id))
            self.assertEqual(session, load(continuation_id, root=root))
            stored = root / f"{continuation_id}.json"
            self.assertEqual(0o600, stored.stat().st_mode & 0o777)
            self.assertEqual(0o700, root.stat().st_mode & 0o777)

            save(continuation_id, session, root=root)
            discard(continuation_id, root=root)
            with self.assertRaisesRegex(PrivateStoreError, "missing or expired"):
                load(continuation_id, root=root)

    def test_cli_returns_a_short_continuation_not_a_transport_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                **os.environ,
                "PLAY_CONTINUATION_DIR": str(Path(directory) / "continuations"),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "bin" / "play-machine"),
                    "session-start",
                    "--stdin",
                    "--json",
                ],
                cwd=ROOT,
                env=environment,
                input=json.dumps(
                    {
                        "run_id": "cli-run",
                        "task_key": "cli-task",
                        "request": {"original": "run hello"},
                    }
                ),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(24, len(payload["continuation_id"]))
            self.assertNotIn("session_token", payload)


if __name__ == "__main__":
    unittest.main()
