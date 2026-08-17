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
            "## Get started for the first time",
            "## Find and run an existing Play",
            "## See what is available",
            "## Turn successful work into a Play",
            "## See how a Play was made",
            "## Work directly for one request",
            "## Route a provider directly in this project",
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
        self.assertIn("There is deliberately no sticky `$play skip` mode", result.stdout)


if __name__ == "__main__":
    unittest.main()
