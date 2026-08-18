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

    def test_skill_uses_compiled_presentations_without_a_second_lookup(self) -> None:
        skill = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()

        self.assertIn("Present returned `presentations`", skill)
        self.assertIn(
            "the returned projection is the entire instruction contract",
            skill.replace("\n", " "),
        )

    def test_whats_new_is_a_no_preflight_no_continuation_fast_path(self) -> None:
        skill = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()
        normalized = skill.replace("\n", " ")

        self.assertIn("play-digest --remember --days 7", skill)
        self.assertIn(
            "do not enter the state machine, run preflight, or create a continuation",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
