from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from scripts.lib.play.guide import render_guide


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "scripts" / "bin" / "play-guide"


class PlayGuideTest(unittest.TestCase):
    def test_default_guide_uses_only_the_selected_harness_prefix(self) -> None:
        rendered = render_guide(harness="claude")

        self.assertIn("**Claude Code Play prefix:** `/play`", rendered)
        self.assertIn("`/play what's new`", rendered)
        self.assertIn("`/play run hello`", rendered)
        self.assertIn("No match     → Play steps aside", rendered)
        self.assertNotIn("`$play run hello`", rendered)
        self.assertNotIn("`/skill:play run hello`", rendered)

    def test_generic_guide_maps_every_prefix(self) -> None:
        rendered = render_guide()

        self.assertIn("`$play` in Codex", rendered)
        self.assertIn("`/skill:play` in Kimi", rendered)
        self.assertIn("`/play` in other supported agents", rendered)

    def test_plain_question_routes_to_running_someone_elses_play(self) -> None:
        rendered = render_guide(
            harness="opencode",
            words=("how", "do", "I", "run", "another", "person's", "Play"),
        )

        self.assertIn("# ◆ Run someone else's Play", rendered)
        self.assertIn("Choosing the result allows inspection", rendered)
        self.assertIn("**Pull and run**", rendered)
        self.assertIn("quietly returns the original request", rendered)

    def test_sources_explain_local_team_and_community_origins(self) -> None:
        rendered = render_guide(harness="codex", words=("sources",))

        self.assertIn("**Your machine**", rendered)
        self.assertIn("**Your teams**", rendered)
        self.assertIn("**The community**", rendered)
        self.assertIn("never automatic permission", rendered)

    def test_quiet_topic_distinguishes_fallback_search_and_explore(self) -> None:
        rendered = render_guide(harness="kimi", words=("no", "match"))

        self.assertIn("# ◆ Play gets out of the way", rendered)
        self.assertIn("No match       → Play stays quiet", rendered)
        self.assertIn("`/skill:play explore <outcome>`", rendered)
        self.assertIn("search-only", rendered)

    def test_command_accepts_a_harness_and_plain_language_lookup(self) -> None:
        result = subprocess.run(
            [str(COMMAND), "--harness", "cursor", "where", "is", "a", "Play", "pulled", "from"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("# ◆ Where Plays come from", result.stdout)
        self.assertIn("**Cursor Play prefix:** `/play`", result.stdout)


if __name__ == "__main__":
    unittest.main()
