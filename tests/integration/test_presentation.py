from __future__ import annotations

import unittest
from pathlib import Path

from scripts.lib.play.presentation import PresentationError, SCHEMA, resolve


class PresentationTest(unittest.TestCase):
    def test_search_state_has_orb_message_and_text_fallback(self) -> None:
        payload = resolve("search", size=64, theme="dark")

        self.assertEqual(SCHEMA, payload["schema"])
        self.assertEqual({"state": "searching", "size": 64, "theme": "dark"}, payload["orb"])
        self.assertIn("Play shelves", payload["message"])
        self.assertTrue(payload["fallback"].endswith(payload["message"]))
        self.assertFalse(payload["terminal"])

    def test_terminal_can_override_trajectory_message(self) -> None:
        payload = resolve("blocked")

        self.assertEqual("breathing", payload["orb"]["state"])
        self.assertIn("knot", payload["message"])
        self.assertTrue(payload["terminal"])

    def test_unknown_machine_state_fails_closed(self) -> None:
        with self.assertRaises(PresentationError):
            resolve("invented_state")

    def test_skill_requires_exact_glyph_fallback_without_renderer(self) -> None:
        skill = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()

        self.assertIn("use the exact stdout", skill)
        self.assertIn("static orb glyph and message", skill)
        self.assertIn("Do not query the mapping with `jq`", skill)
        self.assertIn("Merely bundling `PlayActivity.tsx`", skill)


if __name__ == "__main__":
    unittest.main()
