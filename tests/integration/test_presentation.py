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

    def test_every_eligible_run_executes_before_recurring_offer(self) -> None:
        skill = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()
        normalized = skill.replace("\n", " ")

        self.assertIn(
            "Present the complete result and its verified receipt unchanged",
            normalized,
        )
        self.assertIn(
            "When a run qualifies, ask whether the user wants it to repeat",
            normalized,
        )
        self.assertIn(
            "This includes a first remote pull or replacement and a run of an already-local exact version",
            normalized,
        )
        self.assertIn(
            "Place the literal primary payload and receipt in chat before you run `play recurring probe` or open the picker",
            normalized,
        )
        self.assertIn(
            "A later scheduling request uses the explicit path above",
            normalized,
        )
        self.assertNotIn("Tip: To repeat this Play automatically with Tulving", skill)

    def test_result_delivery_is_user_visible_before_recurring_tools(self) -> None:
        skill = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()
        normalized = skill.replace("\n", " ")

        self.assertIn(
            "Tool, shell, and model-context output does not count as delivery",
            normalized,
        )
        self.assertIn(
            "Copy the exact Markdown for each presentation into a message the user can see",
            normalized,
        )
        self.assertIn(
            "Do not claim that the result was “shown above” unless its literal payload appears in chat",
            normalized,
        )
        self.assertIn(
            "Finish delivery before you call another tool. This includes `play recurring probe` and structured elicitation",
            normalized,
        )
        self.assertIn(
            "If opening a picker could hide the assistant message, end with the complete result and verified receipt",
            normalized,
        )
        self.assertIn("A summary is not delivery", normalized)

    def test_pre_receipt_scheduling_barrier_precedes_every_execution_path(self) -> None:
        skill = (Path(__file__).resolve().parents[2] / "SKILL.md").read_text()
        normalized = skill.replace("\n", " ")
        barrier = skill.index("### Scheduling begins only after the result")

        self.assertLess(barrier, skill.index("If the request explicitly asks to schedule"))
        self.assertLess(barrier, skill.index("## Enter or resume"))
        self.assertIn(
            "Before Play returns a verified successful receipt, never mention scheduling",
            normalized,
        )
        self.assertIn(
            "A domain result called a receipt, such as a ride-share receipt, is not a verified Play receipt",
            normalized,
        )
        self.assertIn(
            "Do not treat a request to pull and run as a scheduling request",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
