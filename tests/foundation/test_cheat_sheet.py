from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "scripts" / "bin" / "play-cheat-sheet"


class CheatSheetTest(unittest.TestCase):
    def test_rendered_sheet_teaches_each_user_job_by_example(self) -> None:
        result = subprocess.run(
            [str(COMMAND)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for heading in (
            "## Pick your path",
            "## Your first minute: become a Playrunner",
            "## Ask for an outcome, not a command",
            "## Know what “Pull and run” means",
            "## Follow the nudges: Playrunner → Playmaker",
            "## Turn your expertise into a Play",
            "## Pocket card",
            "## The three rules worth remembering",
        ):
            self.assertIn(heading, result.stdout)
        for command in (
            "$play settle <capture-handle>",
            "direct: <request>",
            "play-routing --project . add github-direct",
            "play-routing --project . remove github-direct",
        ):
            self.assertIn(command, result.stdout)
        self.assertIn("You:", result.stdout)
        self.assertIn("Play:", result.stdout)
        self.assertIn("The bypass covers inference continuations, delegation, retries, and tool loops", result.stdout)
        self.assertIn("Inspect before you approve", result.stdout)
        self.assertIn("Secrets stay out of chat", result.stdout)


if __name__ == "__main__":
    unittest.main()
