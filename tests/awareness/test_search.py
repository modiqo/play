import pathlib
import sys
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play import search as PLAY_SEARCH


class SearchTest(unittest.TestCase):
    def test_query_normalization_removes_special_characters_and_duplicate_tokens(self):
        query = "Live status? (AI models)—AI models; café's latency!"
        self.assertEqual(
            "live status ai models cafe s latency",
            PLAY_SEARCH.normalize_query(query),
        )

    def test_local_aliases_and_registry_versions_deduplicate_by_canonical_play(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        description = "Live service status"
        local = {
            "flows": [
                {
                    "name": "hello",
                    "path": str(flow_root / "warsaw-rust" / "hello" / "main.ts"),
                    "description": description,
                    "score": 27.4,
                },
                {
                    "name": "hello",
                    "path": str(flow_root / "hello" / "main.ts"),
                    "description": description,
                    "score": 27.4,
                },
            ]
        }
        registry = [
            {
                "owner_slug": "warsaw-rust",
                "skill_name": "hello",
                "skill_description": description,
                "version": "0.0.1",
                "rank": 0.6,
                "status": "approved",
            },
            {
                "owner_slug": "warsaw-rust",
                "skill_name": "hello",
                "skill_description": description,
                "version": "0.1.0",
                "rank": 0.6,
                "status": "approved",
            },
        ]
        results = PLAY_SEARCH.merge_results(local, registry, flow_root, 10, "live service status")
        self.assertEqual(1, len(results))
        self.assertEqual("warsaw-rust/hello", results[0]["reference"])
        self.assertEqual("0.1.0", results[0]["version"])
        self.assertEqual(["local", "registry"], results[0]["sources"])
        self.assertEqual(
            "https://play.modiqo.ai/warsaw-rust/hello@0.1.0", results[0]["uri"]
        )
        self.assertEqual("rote play run warsaw-rust/hello@0.1.0", results[0]["run_command"])
        self.assertEqual(
            "rote play inspect warsaw-rust/hello@0.1.0 --json",
            results[0]["inspect_command"],
        )
        self.assertEqual("found", results[0]["local_availability"])
        self.assertEqual("inspect_required", results[0]["execution_resolution"])

    def test_registry_only_result_discloses_expected_pull_before_selection(self):
        results = PLAY_SEARCH.merge_results(
            {"flows": []},
            [
                {
                    "owner_slug": "alpha",
                    "skill_name": "mail",
                    "skill_description": "Retrieve recent email",
                    "version": "1.0.0",
                    "rank": 1.0,
                    "status": "approved",
                }
            ],
            pathlib.Path("/tmp/example-flows"),
            10,
            "recent email",
        )
        self.assertEqual("not_found", results[0]["local_availability"])
        self.assertEqual("pull_expected", results[0]["execution_resolution"])
        self.assertIn("local pull/install is expected", results[0]["selection_description"])

    def test_local_only_canonical_path_is_not_claimed_as_registry_runnable(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        results = PLAY_SEARCH.merge_results(
            {
                "flows": [
                    {
                        "name": "local-report",
                        "path": str(flow_root / "alpha" / "local-report" / "main.ts"),
                        "description": "Local report",
                        "score": 1.0,
                    }
                ]
            },
            [],
            flow_root,
            10,
            "local report",
        )
        self.assertIsNone(results[0]["reference"])
        self.assertEqual("local-flow-gap", results[0]["hint_kind"])
        self.assertEqual("publish_required", results[0]["execution_resolution"])
        self.assertTrue(results[0]["uri"].startswith("file://"))

    def test_local_and_registry_searches_start_in_parallel(self):
        barrier = threading.Barrier(2)

        def fake_run(command, **_kwargs):
            barrier.wait(timeout=2)
            return {"flows": []} if command[1:3] == ["flow", "search"] else []

        with mock.patch.object(PLAY_SEARCH, "run_json", side_effect=fake_run):
            local, registry = PLAY_SEARCH.search_both("hello", 5)
        self.assertEqual({"flows": []}, local)
        self.assertEqual([], registry)

    def test_play_choices_are_exact_and_exclude_local_only_flows(self):
        choices = PLAY_SEARCH.build_play_choices(
            [
                {
                    "name": "mail",
                    "exact_reference": "alpha/mail@1.0.0",
                    "selection_description": "Inspect mail.",
                },
                {
                    "name": "local",
                    "exact_reference": None,
                    "selection_description": "Publish local.",
                },
            ]
        )
        self.assertEqual(
            [
                {
                    "reference": "alpha/mail@1.0.0",
                    "label": "mail — alpha",
                    "description": "Inspect mail.",
                    "parameters": {},
                }
            ],
            choices,
        )

    def test_markdown_includes_uri_and_next_command(self):
        results = [
            {
                "name": "hello",
                "version": "0.1.0",
                "sources": ["local", "registry"],
                "score": 1.0,
                "uri": "https://play.modiqo.ai/warsaw-rust/hello@0.1.0",
                "run_command": "rote play run warsaw-rust/hello@0.1.0",
                "inspect_command": "rote play inspect warsaw-rust/hello@0.1.0 --json",
                "hint_kind": "play",
                "execution_resolution": "inspect_required",
            }
        ]
        output = PLAY_SEARCH.render_markdown("hello?", "hello", results)
        self.assertIn("URI: https://play.modiqo.ai/warsaw-rust/hello@0.1.0", output)
        self.assertIn("Next: inspect with `rote play inspect", output)
        self.assertIn("requires a separate approval", output)


if __name__ == "__main__":
    unittest.main()
