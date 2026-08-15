import os
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
        self.assertEqual(["local", "remote_private"], results[0]["sources"])
        self.assertEqual(
            "https://play.modiqo.ai/warsaw-rust/hello", results[0]["uri"]
        )
        self.assertEqual("rote play run warsaw-rust/hello", results[0]["run_command"])
        self.assertEqual(
            "rote play inspect warsaw-rust/hello --json",
            results[0]["inspect_command"],
        )
        self.assertEqual("found", results[0]["local_availability"])
        self.assertEqual("run_local", results[0]["execution_resolution"])
        self.assertEqual("local", results[0]["primary_scope"])

    def test_argument_tokens_do_not_dilute_a_complete_name_match(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        local = {
            "flows": [
                {
                    "name": "list-top-committers",
                    "path": str(flow_root / "modiqo" / "list-top-committers" / "main.ts"),
                    "description": "Lists top contributors for a GitHub repository.",
                    "score": 20.0,
                }
            ]
        }
        results = PLAY_SEARCH.merge_results(
            local, [], flow_root, 10, "list top committers for modiqo rote"
        )
        self.assertEqual("full", results[0]["match_classification"])
        results = PLAY_SEARCH.merge_results(
            local, [], flow_root, 10, "list something unrelated entirely here"
        )
        self.assertNotEqual("full", results[0]["match_classification"])

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
        self.assertEqual("pull_required", results[0]["execution_resolution"])
        self.assertEqual("remote_private", results[0]["primary_scope"])
        self.assertIn("pulling requires your approval", results[0]["selection_description"])

    def test_unaddressable_private_record_does_not_abort_other_matches(self):
        results = PLAY_SEARCH.merge_results(
            {"flows": []},
            [
                {
                    "owner_slug": None,
                    "skill_name": "retrieve-rideshare-receipts",
                    "skill_description": "Retrieve rideshare receipts",
                    "version": "0.0.6",
                    "storage_path": "organization_hidden/retrieve/0.0.6/item.flow",
                },
                {
                    "owner_slug": "modiqo",
                    "skill_name": "retrieve-rideshare-receipts",
                    "skill_description": "Retrieve rideshare receipts",
                    "version": "0.1.0",
                    "visibility": "public",
                    "storage_path": "organization_public/retrieve/0.1.0/item.flow",
                },
            ],
            pathlib.Path("/tmp/example-flows"),
            10,
            "rideshare receipts",
        )
        self.assertEqual(1, len(results))
        self.assertEqual(
            "modiqo/retrieve-rideshare-receipts@0.1.0",
            results[0]["exact_reference"],
        )

    def test_catalog_reconciles_live_visibility_by_stable_play_id(self):
        reconciled = PLAY_SEARCH.reconcile_registry_items(
            [
                {
                    "skill_id": "play-123",
                    "owner_slug": "workplace-automation",
                    "skill_name": "retrieve-recent-emails",
                    "skill_description": "Retrieve recent email",
                    "version": "0.1.3",
                    "storage_path": "organization_759/retrieve/0.1.3/item.flow",
                }
            ],
            [
                {
                    "skill_id": "play-123",
                    "owner_id": "org-759",
                    "owner_slug": "workplace-automation",
                    "skill_name": "retrieve-recent-emails",
                    "skill_description": "Retrieve recent email",
                    "visibility": "public",
                }
            ],
        )
        self.assertEqual(1, len(reconciled))
        self.assertEqual("public", reconciled[0]["visibility"])
        self.assertEqual("org-759", reconciled[0]["owner_id"])
        self.assertEqual("remote_public", PLAY_SEARCH.registry_scope(reconciled[0]))

    def test_storage_path_never_grants_public_visibility(self):
        self.assertEqual(
            "remote_private",
            PLAY_SEARCH.registry_scope(
                {"storage_path": "community_legacy/a-play/1.0.0/item.flow"}
            ),
        )

    def test_reorganized_registry_owner_supersedes_stale_local_owner(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        description = "Retrieve recent Gmail messages."
        results = PLAY_SEARCH.merge_results(
            {
                "flows": [
                    {
                        "name": "retrieve-recent-emails",
                        "path": str(
                            flow_root
                            / "modiqo"
                            / "retrieve-recent-emails"
                            / "main.ts"
                        ),
                        "description": description,
                        "score": 20.0,
                    }
                ]
            },
            [
                {
                    "skill_id": "play-123",
                    "owner_slug": "workplace-automation",
                    "skill_name": "retrieve-recent-emails",
                    "skill_description": description,
                    "visibility": "public",
                    "version": "0.1.3",
                }
            ],
            flow_root,
            10,
            "retrieve recent emails",
        )
        self.assertEqual(1, len(results))
        self.assertEqual(
            "workplace-automation/retrieve-recent-emails@0.1.3",
            results[0]["reference"],
        )
        self.assertIn(
            "modiqo/retrieve-recent-emails", results[0]["selection_description"]
        )
        self.assertEqual("remote_public", results[0]["primary_scope"])
        self.assertEqual("not_found", results[0]["local_availability"])
        self.assertEqual("pull_required", results[0]["execution_resolution"])

    def test_local_dag_path_is_exposed_only_as_canonical_reference(self):
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
        self.assertEqual(
            "alpha/local-report",
            results[0]["reference"],
        )
        self.assertEqual("play", results[0]["hint_kind"])
        self.assertEqual("run_local", results[0]["execution_resolution"])
        self.assertEqual(
            "https://play.modiqo.ai/alpha/local-report", results[0]["uri"]
        )
        self.assertEqual(
            "rote play run alpha/local-report",
            results[0]["run_command"],
        )

    def test_legacy_local_path_without_owner_is_not_offered_for_execution(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        results = PLAY_SEARCH.merge_results(
            {
                "flows": [
                    {
                        "name": "legacy-report",
                        "path": str(flow_root / "legacy-report" / "main.ts"),
                        "description": "Legacy report",
                    }
                ]
            },
            [],
            flow_root,
            10,
            "legacy report",
        )
        self.assertEqual([], results)

    def test_catalog_cache_backstops_registry_search_recall(self):
        import json as json_module
        import tempfile

        def fake_run(command, **_kwargs):
            return {"flows": []} if command[1:3] == ["play", "search"] else []

        with tempfile.TemporaryDirectory() as temporary:
            cache_path = pathlib.Path(temporary) / "inbox-cache.json"
            cache_path.write_text(
                json_module.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "fetched_at": "2026-08-11T00:00:00+00:00",
                        "window_days": 7,
                        "summary_line": None,
                        "counts": {"new": 0, "revised": 0},
                        "digest": {},
                        "markdown": None,
                        "catalog": [
                            {
                                "reference": "modiqo/list-top-committers",
                                "name": "list-top-committers",
                                "description": "Lists top contributors for a GitHub repository.",
                                "visibility": "public",
                            }
                        ],
                    }
                )
            )
            with mock.patch.object(PLAY_SEARCH, "run_json", side_effect=fake_run), \
                    mock.patch.dict(
                        os.environ, {"PLAY_INBOX_CACHE_PATH": str(cache_path)}
                    ):
                local, registry = PLAY_SEARCH.search_both(
                    "list top committers for modiqo rote", 5
                )
            self.assertEqual("list-top-committers", registry[0]["skill_name"])
            results = PLAY_SEARCH.merge_results(
                local, registry, pathlib.Path("/tmp/none"), 5,
                "list top committers for modiqo rote",
            )
            self.assertEqual("modiqo/list-top-committers", results[0]["reference"])
            self.assertEqual("full", results[0]["match_classification"])

    def test_local_and_registry_searches_start_in_parallel(self):
        barrier = threading.Barrier(2)
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            barrier.wait(timeout=2)
            return {"flows": []} if command[1:3] == ["play", "search"] else []

        with mock.patch.object(PLAY_SEARCH, "run_json", side_effect=fake_run), \
                mock.patch.dict(
                    os.environ, {"PLAY_INBOX_CACHE_PATH": "/nonexistent/inbox.json"}
                ):
            local, registry = PLAY_SEARCH.search_both("hello", 5)
        self.assertEqual({"flows": []}, local)
        self.assertEqual([], registry)
        self.assertIn(
            ["rote", "play", "search", "hello", "--limit", "50", "--json"], commands
        )
        self.assertIn(
            ["rote", "registry", "play", "search", "hello", "--limit", "50", "--json"],
            commands,
        )

    def test_request_values_are_removed_for_parallel_discovery(self):
        self.assertEqual(
            ["fetch rideshare receipts for month of july 2026", "rideshare receipts"],
            PLAY_SEARCH.discovery_queries(
                "fetch rideshare receipts for month of july 2026"
            ),
        )

    def test_scope_priority_is_local_then_private_then_public(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        description = "Retrieve rideshare receipts"
        local = {
            "flows": [{
                "name": "local-receipts",
                "path": str(flow_root / "local" / "local-receipts" / "main.ts"),
                "description": description,
                "score": 0.1,
            }]
        }
        registry = [
            {
                "owner_slug": "public-hub",
                "skill_name": "public-receipts",
                "skill_description": description,
                "version": "2.0.0",
                "rank": 10.0,
                "status": "approved",
                "visibility": "public",
                "storage_path": "community_123/public-receipts/2.0.0/flow",
            },
            {
                "owner_slug": "private-org",
                "skill_name": "private-receipts",
                "skill_description": description,
                "version": "1.0.0",
                "rank": 1.0,
                "status": "approved",
                "visibility": "private",
                "storage_path": "organization_123/private-receipts/1.0.0/flow",
            },
        ]
        results = PLAY_SEARCH.merge_results(
            local, registry, flow_root, 10, "rideshare receipts"
        )
        self.assertEqual(
            ["local", "remote_private", "remote_public"],
            [result["primary_scope"] for result in results],
        )

    def test_play_choices_include_local_and_remote_runnable_plays(self):
        choices = PLAY_SEARCH.build_play_choices(
            [
                {
                    "name": "mail",
                    "reference": "alpha/mail@1.0.0",
                    "primary_scope": "remote_private",
                    "selection_description": "Inspect mail.",
                },
                {
                    "name": "local",
                    "reference": "/tmp/local/main.ts",
                    "primary_scope": "local",
                    "selection_description": "Run local.",
                },
            ]
        )
        self.assertEqual(
            [
                {
                    "reference": "alpha/mail@1.0.0",
                    "label": "mail — private",
                    "description": "Inspect mail.",
                    "parameters": {},
                },
                {
                    "reference": "/tmp/local/main.ts",
                    "label": "local — local",
                    "description": "Run local.",
                    "parameters": {},
                },
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
                "execution_resolution": "run_local",
            }
        ]
        output = PLAY_SEARCH.render_markdown("hello?", "hello", results)
        self.assertIn("URI: https://play.modiqo.ai/warsaw-rust/hello@0.1.0", output)
        self.assertIn("Next: inspect with `rote play inspect", output)
        self.assertIn("runs it immediately", output)


if __name__ == "__main__":
    unittest.main()
