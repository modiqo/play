from __future__ import annotations

import unittest
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.lib.play.journey import build_graph
from scripts.lib.play.journey_story import SCHEMA, build_story


def activity(sequence: int, kind: str, operation: str, *, effect: str | None = None) -> dict:
    return {
        "sequence": sequence,
        "command_type": "Synthetic",
        "response_refs": [f"@{sequence}"],
        "operation": operation,
        "provider": None,
        "kind": kind,
        "role": "verification" if kind == "evidence" else None,
        "effect": effect,
        "status": "succeeded",
        "duration_ms": sequence * 100,
        "tokens": sequence * 10,
        "tokens_saved": sequence,
        "signature": f"sig-{sequence}",
        "timestamp": None,
    }


class JourneyStoryTest(unittest.TestCase):
    def test_story_preserves_recalled_play_route_and_benefit(self) -> None:
        graph = build_graph(
            {
                "reference": "cap_recalled",
                "intent": "Retrieve recent emails",
                "status": "recorded",
                "origin": {
                    "kind": "recalled_play",
                    "run_id": "run-recalled",
                    "exact_reference": "modiqo/retrieve-recent-emails@0.1.6",
                    "association_basis": "typed_workspace",
                    "exploration_skipped": True,
                },
            },
            activities=[],
            dependencies=[],
            stats={"commands": 0, "responses": 0},
        )
        story = build_story(graph)
        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "references/explore/journey-story.schema.json").read_text()
        )

        Draft202012Validator(schema).validate(story)
        self.assertEqual("recalled_play", story["origin"]["kind"])
        self.assertEqual("known", story["route"]["mode"])
        self.assertTrue(story["route"]["exploration_skipped"])
        self.assertTrue(story["benefit"]["workflow_discovery_avoided"])

    def test_story_is_readable_deterministic_and_lossless_by_reference(self) -> None:
        graph = build_graph(
            {"reference": "cap_story", "intent": "Deploy and verify production", "status": "active"},
            activities=[
                activity(1, "capability", "sh -c"),
                activity(2, "evidence", "sed -n"),
                activity(3, "effect", "git -C", effect="local_write"),
                activity(4, "evidence", "curl"),
                activity(5, "play_candidate", "candidate"),
            ],
            dependencies=[],
            stats={"commands": 5, "responses": 5},
        )
        first = build_story(graph)
        second = build_story(graph)
        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "references/explore/journey-story.schema.json").read_text()
        )

        Draft202012Validator(schema).validate(first)
        self.assertEqual(SCHEMA, first["schema"])
        self.assertEqual(first, second)
        self.assertEqual(len(graph["nodes"]), len(first["chapters"]))
        self.assertEqual(
            {node["id"] for node in graph["nodes"]},
            set(first["audit"]["preserved_chapter_ids"]),
        )
        self.assertEqual("Apply repository changes", first["chapters"][3]["title"])
        self.assertEqual("Verify the completed work", first["chapters"][4]["title"])
        self.assertNotIn("PH", {chapter["title"] for chapter in first["chapters"]})

    def test_story_titles_preserve_operation_specific_meaning(self) -> None:
        graph = build_graph(
            {"reference": "cap_titles", "intent": "Change and verify production", "status": "active"},
            activities=[
                activity(1, "phase", "git -C"),
                activity(2, "phase", "just -f"),
                activity(3, "effect", "git -C", effect="local_write"),
                activity(4, "phase", "curl -fsSL"),
                activity(5, "phase", "Inspect relevant source and context"),
            ],
            dependencies=[],
            stats={"commands": 5, "responses": 5},
        )

        titles = [chapter["title"] for chapter in build_story(graph)["chapters"]]

        self.assertEqual(
            [
                "Requested outcome",
                "Inspect repository state",
                "Run project checks",
                "Apply repository changes",
                "Verify the deployed surface",
                "Review the completed output",
            ],
            titles,
        )


if __name__ == "__main__":
    unittest.main()
