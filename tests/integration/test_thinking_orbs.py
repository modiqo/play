from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MACHINE = ROOT / "references" / "controller" / "machine.yaml"
MAPPING = ROOT / "references" / "integration" / "thinking-orbs.json"
ORB_STATES = {
    "working",
    "searching",
    "solving",
    "listening",
    "connecting",
    "weaving",
    "composing",
    "breathing",
    "shaping",
}


class ThinkingOrbsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = yaml.safe_load(MACHINE.read_text())
        self.mapping = json.loads(MAPPING.read_text())

    def test_every_machine_state_has_exactly_one_orb_presentation(self) -> None:
        machine_states = set(self.machine["states"])
        mapped_states = set(self.mapping["states"])

        self.assertEqual(machine_states, mapped_states)

    def test_all_nine_orbs_have_a_specific_trajectory(self) -> None:
        used = {value["orb"] for value in self.mapping["states"].values()}

        self.assertEqual(ORB_STATES, used)

    def test_declared_prompts_listen_and_terminals_breathe_paused(self) -> None:
        for state, specification in self.machine["states"].items():
            presentation = self.mapping["states"][state]
            if "prompt" in specification:
                self.assertEqual("listening", presentation["orb"], state)
            if state in self.machine["terminal"]:
                self.assertEqual("breathing", presentation["orb"], state)
                self.assertTrue(presentation.get("terminal"), state)

    def test_every_presentation_has_an_accessible_status_label(self) -> None:
        for state, presentation in self.mapping["states"].items():
            self.assertTrue(presentation["label"].strip(), state)


if __name__ == "__main__":
    unittest.main()
