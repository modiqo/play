import os
import pathlib
import sys
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
        self.assertEqual([], results)

    def test_one_character_play_name_typo_still_matches_full_identity(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        local = {
            "flows": [
                {
                    "name": "list-top-committers",
                    "path": str(
                        flow_root / "modiqo" / "list-top-committers" / "main.ts"
                    ),
                    "description": "Lists top contributors for a GitHub repository.",
                    "score": 20.0,
                }
            ]
        }

        misspelled_query = "can you list top commi" + "ters for modiqo rote"
        results = PLAY_SEARCH.merge_results(
            local, [], flow_root, 10, misspelled_query
        )

        self.assertEqual("list-top-committers", results[0]["name"])
        self.assertEqual("full", results[0]["match_classification"])

    def test_short_or_unrelated_tokens_do_not_receive_typo_tolerance(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        local = {
            "flows": [
                {
                    "name": "list-top-committers",
                    "path": str(
                        flow_root / "modiqo" / "list-top-committers" / "main.ts"
                    ),
                    "description": "Lists top contributors for a GitHub repository.",
                    "score": 20.0,
                }
            ]
        }

        results = PLAY_SEARCH.merge_results(
            local, [], flow_root, 10, "lost tap computers for modiqo rote"
        )

        self.assertEqual([], results)

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
            "workplace-automation/retrieve-recent-emails",
            results[0]["reference"],
        )
        self.assertEqual(
            "workplace-automation/retrieve-recent-emails@0.1.3",
            results[0]["exact_reference"],
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
                        "catalog_complete": True,
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
            with mock.patch.object(
                PLAY_SEARCH, "run_json", side_effect=fake_run
            ) as live_search, mock.patch.dict(
                os.environ, {"PLAY_INBOX_CACHE_PATH": str(cache_path)}
            ):
                local, registry = PLAY_SEARCH.search_both(
                    "list top committers for modiqo rote", 5
                )
            self.assertTrue(
                all("--source" not in call.args[0] for call in live_search.call_args_list)
            )
            self.assertEqual("list-top-committers", registry[0]["skill_name"])
            results = PLAY_SEARCH.merge_results(
                local, registry, pathlib.Path("/tmp/none"), 5,
                "list top committers for modiqo rote",
            )
            self.assertEqual("modiqo/list-top-committers", results[0]["reference"])
            self.assertEqual("full", results[0]["match_classification"])

    def test_verified_catalog_recovers_malformed_live_search_for_rideshare_query(self):
        import json as json_module
        import tempfile

        query = (
            "can you retrieve my rideshare receipts between july 15 "
            "and august 15th 2026"
        )
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = pathlib.Path(temporary) / "inbox-cache.json"
            cache_path.write_text(
                json_module.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "catalog_complete": True,
                        "catalog": [
                            {
                                "reference": "modiqo/retrieve-rideshare-receipts",
                                "name": "retrieve-rideshare-receipts",
                                "description": (
                                    "Retrieves rideshare receipts between two dates "
                                    "from Uber, Lyft, and Waymo."
                                ),
                                "visibility": "public",
                                "skill_id": "rideshare-play",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                PLAY_SEARCH,
                "run_json",
                side_effect=PLAY_SEARCH.SearchError("returned malformed JSON"),
            ), mock.patch.dict(
                os.environ, {"PLAY_INBOX_CACHE_PATH": str(cache_path)}
            ):
                local, registry = PLAY_SEARCH.search_both(
                    PLAY_SEARCH.normalize_query(query), 5
                )

        results = PLAY_SEARCH.merge_results(
            local,
            registry,
            pathlib.Path("/tmp/none"),
            5,
            PLAY_SEARCH.normalize_query(query),
        )
        self.assertEqual("modiqo/retrieve-rideshare-receipts", results[0]["reference"])
        self.assertEqual("full", results[0]["match_classification"])
        self.assertEqual("complete", local["source_health"]["catalog_cache"])
        self.assertEqual("cached_with_local", local["source_health"]["mode"])
        self.assertTrue(local["source_health"]["live_errors"])
        self.assertTrue(
            all(
                error["source"] == "local"
                for error in local["source_health"]["live_errors"]
            )
        )

    def test_cached_feed_returns_only_the_adequate_landing_page_match(self):
        import json as json_module
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            cache_path = pathlib.Path(temporary) / "inbox-cache.json"
            cache_path.write_text(
                json_module.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "catalog_complete": True,
                        "catalog": [
                            {
                                "reference": "modiqo/landing-page-assessment",
                                "name": "landing-page-assessment",
                                "description": "Assess landing-page messaging and readiness.",
                                "visibility": "public",
                                "version": "0.3.2",
                                "labels": ["Marketing"],
                                "tags": ["job-landing-page-review"],
                                "adapters": ["crucible"],
                            },
                            {
                                "reference": "modiqo/archive-analytics",
                                "name": "archive-analytics",
                                "description": "Analyze archived agent telemetry.",
                                "visibility": "private",
                            },
                            {
                                "reference": "modiqo/create-github-issue",
                                "name": "create-github-issue",
                                "description": "Create an issue on GitHub.",
                                "visibility": "private",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                    PLAY_SEARCH, "run_json", return_value={"flows": []}
            ) as live_search, \
                    mock.patch.dict(
                        os.environ, {"PLAY_INBOX_CACHE_PATH": str(cache_path)}
                    ):
                local, registry = PLAY_SEARCH.search_both(
                    "find an available landing page readiness play", 5
                )

        self.assertEqual(2, live_search.call_count)
        self.assertTrue(
            all(
                call.args[0][1:3] == ["play", "search"]
                for call in live_search.call_args_list
            )
        )
        results = PLAY_SEARCH.merge_results(
            local,
            registry,
            pathlib.Path("/tmp/none"),
            5,
            "find an available landing page readiness play",
        )
        self.assertEqual(
            ["modiqo/landing-page-assessment"],
            [result["reference"] for result in results],
        )
        self.assertEqual("full", results[0]["match_classification"])

    def test_complete_catalog_still_merges_local_installed_plays(self):
        import json as json_module
        import tempfile

        flow_root = pathlib.Path("/tmp/example-flows")
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = pathlib.Path(temporary) / "inbox-cache.json"
            cache_path.write_text(
                json_module.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "catalog_complete": True,
                        "catalog": [],
                    }
                ),
                encoding="utf-8",
            )
            local_result = {
                "flows": [
                    {
                        "name": "local-report",
                        "path": str(flow_root / "acme" / "local-report" / "main.ts"),
                        "description": "Create a local report",
                        "score": 1.0,
                    }
                ]
            }
            with mock.patch.object(
                PLAY_SEARCH, "run_json", return_value=local_result
            ), mock.patch.dict(
                os.environ, {"PLAY_INBOX_CACHE_PATH": str(cache_path)}
            ):
                local, registry = PLAY_SEARCH.search_both(
                    "local report", 5, flow_root=flow_root
                )

        results = PLAY_SEARCH.merge_results(
            local, registry, flow_root, 5, "local report"
        )
        self.assertEqual(["acme/local-report"], [item["reference"] for item in results])
        self.assertEqual("local", results[0]["primary_scope"])

    def test_cached_adapter_associations_find_latest_unique_plays(self):
        catalog = [
            {
                "owner_slug": "modiqo",
                "skill_name": name,
                "skill_description": description,
                "visibility": "public",
                "version": version,
                "adapters": ["crucible"],
                "tags": ["tool-crucible"],
            }
            for name, description, version in (
                (
                    "founder-daily-operating-brief",
                    "Rank founder priorities.",
                    "0.1.2",
                ),
                (
                    "landing-page-assessment",
                    "Assess landing-page messaging.",
                    "0.3.2",
                ),
                (
                    "pricing-page-assessment",
                    "Assess pricing-page decisions.",
                    "0.3.3",
                ),
            )
        ]
        catalog.append(
            {
                "owner_slug": "modiqo",
                "skill_name": "archive-analytics",
                "skill_description": "Analyze archives.",
                "visibility": "private",
                "version": "1.0.0",
                "adapters": ["duckdb"],
            }
        )

        results = PLAY_SEARCH.merge_results(
            {"flows": []},
            catalog,
            pathlib.Path("/tmp/none"),
            10,
            "what are the heavybit crucible related plays",
        )

        self.assertEqual(
            {
                "modiqo/founder-daily-operating-brief",
                "modiqo/landing-page-assessment",
                "modiqo/pricing-page-assessment",
            },
            {result["reference"] for result in results},
        )
        self.assertTrue(
            all(result["matched_adapters"] == ["crucible"] for result in results)
        )
        self.assertNotIn(
            "modiqo/archive-analytics",
            {result["reference"] for result in results},
        )

    def test_complete_cache_miss_is_confirmed_by_live_registry_search(self):
        import json as json_module
        import tempfile

        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            if "--source" not in command:
                return {"flows": []}
            return {
                "schema": "rote.remote-play-search.v1",
                "items": [
                    {
                        "play_id": "remote-only",
                        "reference": "partner/receipt-export@0.4.0",
                        "owner": {"slug": "partner", "kind": "organization"},
                        "name": "receipt-export",
                        "description": "Export rideshare receipts.",
                        "version": "0.4.0",
                        "visibility": "public",
                        "status": "released",
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as temporary:
            cache_path = pathlib.Path(temporary) / "inbox-cache.json"
            cache_path.write_text(
                json_module.dumps(
                    {
                        "schema": "play.inbox-cache/v1",
                        "catalog_complete": True,
                        "catalog": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                PLAY_SEARCH, "run_json", side_effect=fake_run
            ), mock.patch.dict(
                os.environ, {"PLAY_INBOX_CACHE_PATH": str(cache_path)}
            ):
                local, registry = PLAY_SEARCH.search_both(
                    "rideshare receipt export", 5
                )

        self.assertEqual("live_after_cache_miss", local["source_health"]["mode"])
        self.assertEqual("receipt-export", registry[0]["skill_name"])
        self.assertTrue(any("--source" in command for command in commands))

    def test_malformed_live_search_without_verified_catalog_fails_closed(self):
        with mock.patch.object(
            PLAY_SEARCH,
            "run_json",
            side_effect=PLAY_SEARCH.SearchError("returned malformed JSON"),
        ), mock.patch.dict(
            os.environ, {"PLAY_INBOX_CACHE_PATH": "/nonexistent/inbox.json"}
        ):
            with self.assertRaisesRegex(
                PLAY_SEARCH.SearchError, "no verified complete catalog cache"
            ):
                PLAY_SEARCH.search_both("rideshare receipts", 5)

    def test_live_search_accepts_same_typed_rote_result_envelope_as_catalog(self):
        import subprocess

        def typed_result(command, **_kwargs):
            if "--source" not in command:
                payload = '{"flows":[]}'
            else:
                payload = '{"schema":"rote.remote-play-search.v1","items":[]}'
            return subprocess.CompletedProcess(
                command,
                0,
                f"@@status\nok: search ready\n\n@@result\n{payload}\n\n@@next\n- continue\n",
                "",
            )

        with mock.patch(
            "play.commands.subprocess.run", side_effect=typed_result
        ), mock.patch.dict(
            os.environ, {"PLAY_INBOX_CACHE_PATH": "/nonexistent/inbox.json"}
        ):
            local, registry = PLAY_SEARCH.search_both("rideshare receipts", 5)
        self.assertEqual([], local["flows"])
        self.assertEqual([], registry)
        self.assertEqual([], local["source_health"]["live_errors"])

    def test_cache_miss_runs_live_accessible_registry_search(self):
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            if "--source" not in command:
                return {"flows": []}
            return {
                "schema": "rote.remote-play-search.v1",
                "items": [
                    {
                        "play_id": "play-123",
                        "reference": "acme/hello@1.2.3",
                        "owner": {"kind": "organization", "slug": "acme"},
                        "name": "hello",
                        "description": "Say hello to a customer.",
                        "version": "1.2.3",
                        "visibility": "private",
                        "status": "released",
                        "rank": 0.9,
                        "tags": ["greeting"],
                        "requires_adapters": ["slack"],
                    }
                ],
            }

        with mock.patch.object(PLAY_SEARCH, "run_json", side_effect=fake_run), \
                mock.patch.dict(
                    os.environ, {"PLAY_INBOX_CACHE_PATH": "/nonexistent/inbox.json"}
                ):
            local, registry = PLAY_SEARCH.search_both("hello", 5)
        self.assertEqual([], local["flows"])
        self.assertEqual("unavailable", local["source_health"]["catalog_cache"])
        self.assertEqual("live_after_cache_miss", local["source_health"]["mode"])
        self.assertEqual("acme", registry[0]["owner_slug"])
        self.assertEqual("hello", registry[0]["skill_name"])
        self.assertEqual(["slack"], registry[0]["adapters"])
        self.assertIn(
            ["rote", "play", "search", "hello", "--limit", "50", "--json"], commands
        )
        self.assertIn(
            [
                "rote", "play", "search", "hello",
                "--source", "registry", "--scope", "accessible",
                "--limit", "50", "--json",
            ],
            commands,
        )

    def test_request_values_are_removed_for_parallel_discovery(self):
        self.assertEqual(
            ["fetch rideshare receipts for month of july 2026", "rideshare receipts"],
            PLAY_SEARCH.discovery_queries(
                "fetch rideshare receipts for month of july 2026"
            ),
        )

    def test_argument_values_are_stripped_before_search(self):
        self.assertEqual(
            "assess the pricing page at",
            PLAY_SEARCH.outcome_query(
                "Assess the pricing page at https://modiqo.ai/pricing"
            ),
        )
        self.assertEqual(
            "summarize prs for in since",
            PLAY_SEARCH.outcome_query(
                "summarize PRs for @octocat in ~/src/repo since 2026-08-01 \"urgent\""
            ),
        )
        self.assertEqual(
            "email receipts for",
            PLAY_SEARCH.outcome_query("email receipts for person@example.com"),
        )
        # A request that is only an argument still yields a searchable query.
        self.assertEqual(
            "https modiqo ai pricing",
            PLAY_SEARCH.outcome_query("https://modiqo.ai/pricing"),
        )

    def test_relaxed_registry_query_joins_outcome_tokens_with_or(self):
        self.assertEqual(
            "assess OR pricing OR page",
            PLAY_SEARCH.relaxed_registry_query("assess the pricing page at"),
        )
        self.assertIsNone(PLAY_SEARCH.relaxed_registry_query("pricing"))

    def test_intent_paraphrase_with_target_url_still_finds_the_play(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        registry = [
            {
                "owner_slug": "heavybit-crucible",
                "skill_name": "pricing-page-assessment",
                "skill_description": "Is my pricing page helping or hurting?",
                "visibility": "public",
                "version": "0.4.2",
                "status": "approved",
            }
        ]
        for query in (
            "Assess the pricing page at https://modiqo.ai/pricing",
            "assess the pricing page at https modiqo ai pricing",
            "can you conduct pricing page assessment on https://modiqo.ai/pricing",
        ):
            results = PLAY_SEARCH.merge_results(
                {"flows": []}, registry, flow_root, 10, query
            )
            self.assertEqual(
                ["heavybit-crucible/pricing-page-assessment"],
                [result["reference"] for result in results],
                query,
            )
            self.assertEqual("full", results[0]["match_classification"], query)
        results = PLAY_SEARCH.merge_results(
            {"flows": []}, registry, flow_root, 10, "list something unrelated entirely"
        )
        self.assertEqual([], results)

    def test_best_of_several_phrasings_scores_each_play(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        registry = [
            {
                "owner_slug": "heavybit-crucible",
                "skill_name": "pricing-page-assessment",
                "skill_description": "Is my pricing page helping or hurting?",
                "visibility": "public",
                "version": "0.4.2",
            }
        ]
        results = PLAY_SEARCH.merge_results(
            {"flows": []},
            registry,
            flow_root,
            10,
            ["evaluate the plans grid", "pricing page assessment for https://modiqo.ai/pricing"],
        )
        self.assertEqual("full", results[0]["match_classification"])
        self.assertEqual(1.0, results[0]["coverage"])

    def test_live_search_unwraps_rote_machine_envelope_and_empty_pages(self):
        import subprocess

        def typed_result(command, **_kwargs):
            if "--source" not in command:
                payload = (
                    '{"schema":1,"ok":true,"data":{"status":{"ok":true},'
                    '"result":{"fields":{"query":"x","reason":"no_plays_directory","total":"0"}}}}'
                )
            elif "OR" in " ".join(command):
                payload = (
                    '{"schema":1,"ok":true,"data":{"result":{"schema":"rote.remote-play-search.v1",'
                    '"page":{"count":1,"next_cursor":null},"items":[{"reference":'
                    '"heavybit-crucible/pricing-page-assessment@0.4.2","name":"pricing-page-assessment",'
                    '"description":"Is my pricing page helping or hurting?","visibility":"public",'
                    '"version":"0.4.2","status":"approved","owner":{"slug":"heavybit-crucible"}}]}}}'
                )
            else:
                payload = (
                    '{"schema":1,"ok":true,"data":{"result":{"schema":"rote.remote-play-search.v1",'
                    '"page":{"count":0,"next_cursor":null},"items":[]}}}'
                )
            return subprocess.CompletedProcess(command, 0, payload, "")

        with mock.patch(
            "play.commands.subprocess.run", side_effect=typed_result
        ), mock.patch.dict(
            os.environ, {"PLAY_INBOX_CACHE_PATH": "/nonexistent/inbox.json"}
        ):
            local, registry = PLAY_SEARCH.search_both("assess the pricing page at", 5)
        self.assertEqual([], local["flows"])
        self.assertEqual([], local["source_health"]["live_errors"])
        self.assertEqual("live_after_cache_miss", local["source_health"]["mode"])
        self.assertEqual(
            ["heavybit-crucible"], [item["owner_slug"] for item in registry]
        )

    def test_argument_values_never_create_a_match(self):
        """A URL, e-mail, or handle that happens to contain Play vocabulary is not intent."""
        flow_root = pathlib.Path("/tmp/example-flows")
        registry = [
            {
                "owner_slug": "heavybit-crucible",
                "skill_name": "pricing-page-assessment",
                "skill_description": "Is my pricing page helping or hurting?",
                "visibility": "public",
                "version": "0.4.2",
            }
        ]
        for query in (
            "https://modiqo.ai/pricing",
            "send a note to pricing@example.com",
            "open ~/docs/pricing-page-assessment.md",
            "ping @pricing-page on slack",
        ):
            results = PLAY_SEARCH.merge_results(
                {"flows": []}, registry, flow_root, 10, query
            )
            self.assertEqual([], results, query)

    def test_or_relaxed_registry_hits_are_still_filtered_by_coverage(self):
        """OR-joined registry queries widen recall; scoring must still reject weak hits."""
        flow_root = pathlib.Path("/tmp/example-flows")
        registry = [
            {
                "owner_slug": "acme",
                "skill_name": "page-speed-audit",
                "skill_description": "Audits page load performance.",
                "visibility": "public",
                "version": "1.0.0",
            },
            {
                "owner_slug": "acme",
                "skill_name": "competitor-pricing-scrape",
                "skill_description": "Scrapes competitor pricing tables.",
                "visibility": "public",
                "version": "1.0.0",
            },
        ]
        results = PLAY_SEARCH.merge_results(
            {"flows": []},
            registry,
            flow_root,
            10,
            "Assess the pricing page at https://modiqo.ai/pricing",
        )
        self.assertEqual([], results)

    def test_stem_sharing_is_bounded_to_real_inflections(self):
        from play.normalize import token_is_covered

        self.assertTrue(token_is_covered("assessment", {"assess"}))
        self.assertTrue(token_is_covered("assess", {"assessment"}))
        self.assertTrue(token_is_covered("summarize", {"summary"}))
        self.assertTrue(token_is_covered("receipts", {"receipt"}))
        self.assertFalse(token_is_covered("internal", {"interval"}))
        self.assertFalse(token_is_covered("assess", {"asset"}))
        self.assertFalse(token_is_covered("pricing", {"price"}))
        self.assertFalse(token_is_covered("page", {"pages"}))  # short tokens stay exact

    def test_filler_only_intent_matches_nothing(self):
        flow_root = pathlib.Path("/tmp/example-flows")
        registry = [
            {
                "owner_slug": "heavybit-crucible",
                "skill_name": "pricing-page-assessment",
                "skill_description": "Is my pricing page helping or hurting?",
                "visibility": "public",
                "version": "0.4.2",
            }
        ]
        results = PLAY_SEARCH.merge_results(
            {"flows": []}, registry, flow_root, 10, "can you do this for me please"
        )
        self.assertEqual([], results)

    def test_scope_priority_is_local_then_private_then_public_then_baseline(self):
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
            {
                "owner_slug": "modiqo",
                "skill_name": "baseline-receipts",
                "skill_description": description,
                "version": "3.0.0",
                "rank": 20.0,
                "status": "approved",
                "visibility": "public",
                "catalog_tier": "public_baseline",
            },
        ]
        results = PLAY_SEARCH.merge_results(
            local, registry, flow_root, 10, "rideshare receipts"
        )
        self.assertEqual(
            ["local", "remote_private", "remote_public", "remote_baseline"],
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
                "uri": "https://play.modiqo.ai/warsaw-rust/hello",
                "run_command": "rote play run warsaw-rust/hello",
                "inspect_command": "rote play inspect warsaw-rust/hello --json",
                "hint_kind": "play",
                "execution_resolution": "run_local",
            }
        ]
        output = PLAY_SEARCH.render_markdown("hello?", "hello", results)
        self.assertIn("URI: https://play.modiqo.ai/warsaw-rust/hello", output)
        self.assertIn("Next: inspect with `rote play inspect", output)
        self.assertIn("runs it immediately", output)


if __name__ == "__main__":
    unittest.main()
