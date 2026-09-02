from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.digest import (
    _cached_public_fallback,
    _fresh_cached_digest,
    _upgrade_cached_discovery,
    build_digest,
    classify_updates,
    collect_digest,
    merge_public_baseline,
    rank_public,
    render_markdown,
    supports_play_discovery,
    main,
)
from play.public_trends import PublicStatsBatch
from play.registry import Organization, RegistryReadError
from play.timewindow import TimeWindowError


class DigestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 8, 3, tzinfo=timezone.utc)
        self.end = datetime(2026, 8, 4, tzinfo=timezone.utc)

    def test_classifies_new_and_revised_without_crossing_org_boundaries(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "new-play",
                    "visibility": "private",
                    "created_at": "2026-08-03T04:00:00+00:00",
                    "updated_at": "2026-08-03T04:00:00+00:00",
                    "default_parameters": {"days": 7},
                },
                {
                    "name": "revised-play",
                    "visibility": "public",
                    "created_at": "2026-07-01T04:00:00+00:00",
                    "latest_version_created_at": "2026-08-03T06:00:00+00:00",
                    "updated_at": "2026-08-03T06:00:00+00:00",
                },
            ]
        }
        new, revised = classify_updates(grouped, self.start, self.end)
        self.assertEqual(["alpha/new-play"], [item["reference"] for item in new])
        self.assertEqual(["alpha/revised-play"], [item["reference"] for item in revised])
        self.assertEqual("private", new[0]["visibility"])
        self.assertEqual({"days": 7}, new[0]["parameters"])

    def test_public_ranking_is_labeled_as_lifetime_downloads(self) -> None:
        public = [
            ("beta", {"name": "second", "visibility": "public", "download_count": 2}),
            ("alpha", {"name": "first", "visibility": "public", "download_count": 8}),
            ("private", {"name": "hidden", "visibility": "private", "download_count": 99}),
        ]
        ranked, contract = rank_public(public, 5)
        self.assertEqual(["alpha/first", "beta/second"], [item["reference"] for item in ranked])
        self.assertEqual("lifetime_downloads", contract["metric"])
        self.assertNotIn("trending", contract["label"].casefold())
        self.assertTrue(all(item["visibility"] == "public" for item in ranked))
        self.assertTrue(all(item["parameters"] == {} for item in ranked))

    def test_digest_reports_personal_stats_as_unavailable_not_zero(self) -> None:
        digest = build_digest(
            [Organization("alpha", "Alpha")],
            {"alpha": []},
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
        )
        self.assertEqual("unavailable", digest["personal_stats"]["status"])
        self.assertTrue(digest["ranking"]["complete"])
        self.assertEqual("unavailable", digest["ranking"]["global_status"])
        self.assertEqual("play.digest-checkpoint/v1", digest["next_checkpoint"]["schema"])

    def test_updated_at_alone_does_not_claim_a_released_revision(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "metadata-only",
                    "visibility": "public",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "updated_at": "2026-08-03T10:00:00+00:00",
                }
            ]
        }
        new, revised = classify_updates(grouped, self.start, self.end)
        self.assertEqual([], new)
        self.assertEqual([], revised)
        digest = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
        )
        self.assertFalse(digest["org_updates"]["revised_complete"])
        self.assertIn("Revisions are unavailable", render_markdown(digest))
        self.assertIn("No new publications were found", render_markdown(digest))
        self.assertIn("released-version timestamps", render_markdown(digest))

    def test_inspected_update_keeps_latest_selector_and_resolved_version(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "new-play",
                    "visibility": "private",
                    "created_at": "2026-08-03T04:00:00+00:00",
                    "updated_at": "2026-08-03T04:00:00+00:00",
                }
            ]
        }
        digest = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
            update_inspections={
                "alpha/new-play": {
                    "reference": "alpha/new-play",
                    "exact_reference": "alpha/new-play@1.1.0",
                    "version": "1.1.0",
                    "default_parameters": {"days": "7"},
                }
            },
        )
        item = digest["org_updates"]["new"][0]
        self.assertTrue(item["actionable"])
        self.assertEqual("alpha/new-play", item["reference"])
        self.assertEqual("alpha/new-play@1.1.0", item["resolved_reference"])
        self.assertEqual({"days": "7"}, item["parameters"])

    def test_whats_new_lists_sampled_public_cards_directly(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "weekly-report",
                    "description": "Original description",
                    "visibility": "public",
                    "created_at": "2026-08-03T04:00:00+00:00",
                    "latest_version_created_at": "2026-08-03T04:00:00+00:00",
                }
            ]
        }
        digest = build_digest(
            [Organization("alpha", "Alpha Team")],
            grouped,
            [
                (
                    "alpha",
                    {
                        "name": "weekly-report",
                        "description": "A concise weekly customer report.",
                        "visibility": "public",
                        "download_count": 3,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
            update_metadata={
                "alpha/weekly-report": {
                    "description": "A concise weekly customer report.",
                    "creator_name": "Alice Example",
                    "creator_status": "available",
                    "version": "1.0.0",
                }
            },
        )
        rendered = render_markdown(digest)
        self.assertIn("# What’s new in Plays", rendered)
        self.assertIn("1 new or revised Play", rendered)
        self.assertIn("weekly-report", rendered)
        self.assertIn("`play run hello`", rendered)
        self.assertIn("`$play run hello`", rendered)
        self.assertIn("`/play run hello`", rendered)
        self.assertIn("`/skill:play run hello`", rendered)
        self.assertIn("`run hello`", rendered)
        self.assertIn("Play stays out of the way", rendered)
        self.assertNotIn("| Play |", rendered)
        self.assertEqual("unavailable", digest["capabilities"]["run_metrics"]["status"])

    def test_ranking_reports_partial_inspection_without_inventing_global_coverage(self) -> None:
        ranked, contract = rank_public(
            [("alpha", {"name": "one", "visibility": "public", "download_count": 3})],
            5,
            source_complete=False,
            source_errors=["beta/two: inspect timed out"],
            candidate_count=2,
            omitted_count=1,
        )
        self.assertEqual(["alpha/one"], [item["reference"] for item in ranked])
        self.assertFalse(contract["complete"])
        self.assertEqual("authorized_organizations", contract["scope"])
        self.assertEqual("unavailable", contract["global_status"])
        self.assertEqual(1, contract["omitted_count"])

    def test_public_stats_are_grouped_by_owner_and_show_both_counters(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "exact_reference": "modiqo/hello@0.1.0",
                        "owner_kind": "org",
                        "download_count": 7,
                        "install_count": 2,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
            ranking_fetch_elapsed_ms=15.25,
            ranking_fetch_workers=4,
        )
        self.assertEqual("modiqo", digest["public_groups"][0]["owner"])
        self.assertEqual("org", digest["public_groups"][0]["owner_kind"])
        self.assertEqual(1, digest["ranking"]["eligible_count"])
        self.assertEqual(1, digest["ranking"]["organization_count"])
        self.assertEqual(1, digest["sample"]["sampled_count"])
        self.assertEqual("random", digest["sample"]["strategy"])
        self.assertEqual("modiqo/hello", digest["public_sample"][0]["reference"])
        self.assertEqual("modiqo/hello", digest["public_top"][0]["base_reference"])
        self.assertEqual("modiqo/hello", digest["public_top"][0]["reference"])
        self.assertEqual(
            "modiqo/hello@0.1.0", digest["public_top"][0]["exact_reference"]
        )
        self.assertEqual("parallel", digest["ranking"]["fetch"]["mode"])
        self.assertEqual(15.25, digest["ranking"]["fetch"]["elapsed_ms"])
        rendered = render_markdown(digest)
        self.assertIn("1 runnable public Play", rendered)
        self.assertIn("## 1 Play to explore", rendered)
        self.assertIn("**hello**", rendered)
        self.assertIn("Counts cover runnable public cards", rendered)

    def test_first_digest_congratulates_before_the_summary(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        digest["memory"] = {"status": "initial"}
        rendered = render_markdown(digest)
        self.assertTrue(rendered.startswith("**Nice—you’ve taken the first step."))
        self.assertLess(rendered.index("taken the first step"), rendered.index("What’s new"))

    def test_partial_catalog_uses_at_least_language(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
            ranking_complete=False,
            ranking_omitted_count=1,
        )
        self.assertIn("at least **1 runnable public Play**", render_markdown(digest))

    def test_legacy_cached_digest_without_random_sample_is_not_discovery_compatible(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        self.assertTrue(supports_play_discovery(digest))
        digest.pop("public_sample")
        self.assertFalse(supports_play_discovery(digest))

    def test_fresh_legacy_catalog_upgrades_locally_without_registry_refresh(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        digest.pop("public_sample")
        digest.pop("sample")

        upgraded = _upgrade_cached_discovery(
            digest,
            [
                {
                    "reference": "modiqo/hello",
                    "name": "hello",
                    "description": "Safe first Play",
                    "visibility": "public",
                }
            ],
        )

        self.assertIsNotNone(upgraded)
        assert upgraded is not None
        self.assertTrue(supports_play_discovery(upgraded))
        self.assertEqual("modiqo/hello", upgraded["public_sample"][0]["reference"])

    def test_fresh_cache_is_rejected_after_authorized_org_scope_changes(self) -> None:
        digest = build_digest(
            [Organization("alpha", "Alpha", "org-alpha")],
            {"alpha": []},
            [],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        cache = {
            "schema": "play.inbox-cache/v1",
            "window_days": 7,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "authority_sha256": "sha256:" + "0" * 64,
            "digest": digest,
        }

        with patch("play.inbox_cache.read_cache", return_value=cache):
            cached = _fresh_cached_digest(
                days=7,
                organizations=[
                    Organization("alpha", "Alpha", "org-alpha"),
                    Organization("new-org", "New Org", "org-new"),
                ],
            )

        self.assertIsNone(cached)

    def test_registry_network_failure_uses_only_verified_public_cache(self) -> None:
        digest = build_digest(
            [Organization("private-org", "Private Org", "org-private")],
            {
                "private-org": [
                    {
                        "name": "internal-report",
                        "visibility": "private",
                        "created_at": "2026-08-03T04:00:00+00:00",
                        "latest_version_created_at": "2026-08-03T04:00:00+00:00",
                    }
                ]
            },
            [
                (
                    "public-owner",
                    {
                        "name": "hello",
                        "description": "A safe public Play.",
                        "visibility": "public",
                        "status": "released",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        cache = {
            "schema": "play.inbox-cache/v1",
            "window_days": 7,
            "fetched_at": "2026-08-28T12:00:00+00:00",
            "catalog_complete": True,
            "catalog_sha256": "sha256:" + "a" * 64,
            "digest": digest,
            "public_catalog": [
                {
                    "reference": "public-owner/hello",
                    "name": "hello",
                    "visibility": "public",
                }
            ],
        }
        error = RegistryReadError(
            "Invalid configuration: error sending request for url; "
            "If authentication issue, run: rote login"
        )

        with patch("play.inbox_cache.read_cache", return_value=cache):
            fallback = _cached_public_fallback(days=7, error=error)

        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual([], fallback["organizations"])
        self.assertEqual([], fallback["org_updates"]["new"])
        self.assertEqual([], fallback["org_updates"]["revised"])
        self.assertEqual("public_cache_only", fallback["availability"]["status"])
        self.assertEqual("network", fallback["availability"]["reason"])
        self.assertEqual("degraded", fallback["memory"]["status"])
        rendered = render_markdown(fallback)
        self.assertIn("last verified public Play cache", rendered)
        self.assertIn("Private and organization-specific updates are unavailable", rendered)
        self.assertNotIn("rote login", rendered)
        self.assertNotIn("private-org", rendered)
        self.assertNotIn("internal-report", rendered)

    def test_public_cache_fallback_does_not_advance_digest_memory(self) -> None:
        digest = build_digest(
            [],
            {},
            [
                (
                    "public-owner",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "status": "released",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        cache = {
            "schema": "play.inbox-cache/v1",
            "window_days": 7,
            "fetched_at": "2026-08-28T12:00:00+00:00",
            "catalog_complete": True,
            "catalog_sha256": "sha256:" + "b" * 64,
            "digest": digest,
            "public_catalog": [
                {
                    "reference": "public-owner/hello",
                    "name": "hello",
                    "visibility": "public",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "digest-state.json"
            stdout = StringIO()
            stderr = StringIO()
            with patch(
                "play.digest.load_organizations",
                side_effect=RegistryReadError("401 unauthorized: session expired"),
            ), patch("play.inbox_cache.read_cache", return_value=cache), redirect_stdout(
                stdout
            ), redirect_stderr(stderr):
                result = main(
                    ["--remember", "--days", "7", "--state", str(state)]
                )

            self.assertEqual(0, result, stderr.getvalue())
            self.assertFalse(state.exists())
            self.assertIn("Run `rote login`", stdout.getvalue())

    def test_registry_failure_without_public_cache_reports_specific_guidance(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with patch(
            "play.digest.load_organizations",
            side_effect=RegistryReadError("error sending request for url"),
        ), patch("play.inbox_cache.read_cache", return_value=None), redirect_stdout(
            stdout
        ), redirect_stderr(stderr):
            result = main(["--remember", "--days", "7"])

        self.assertEqual(1, result)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("network", stderr.getvalue().casefold())
        self.assertNotIn("rote login", stderr.getvalue())

    def test_cached_digest_with_version_pinned_catalog_choice_is_refreshed(self) -> None:
        digest = build_digest(
            [Organization("modiqo", "Modiqo")],
            {"modiqo": []},
            [
                (
                    "modiqo",
                    {
                        "name": "hello",
                        "visibility": "public",
                        "exact_reference": "modiqo/hello@0.2.0",
                        "download_count": 1,
                    },
                )
            ],
            start=self.start,
            end=self.end,
            public_limit=10,
        )
        self.assertTrue(supports_play_discovery(digest))
        digest["public_sample"][0]["reference"] = "modiqo/hello@0.2.0"
        self.assertFalse(supports_play_discovery(digest))

    def test_random_sample_caps_at_ten_and_is_not_download_ranked(self) -> None:
        grouped = {"modiqo": []}
        public = [
            (
                "modiqo",
                {
                    "name": f"play-{index:02d}",
                    "visibility": "public",
                    "download_count": 100 - index,
                },
            )
            for index in range(12)
        ]
        with patch("play.digest.random.SystemRandom") as system_random:
            system_random.return_value.sample.side_effect = (
                lambda population, count: list(reversed(population))[:count]
            )
            digest = build_digest(
                [Organization("modiqo", "Modiqo")],
                grouped,
                public,
                start=self.start,
                end=self.end,
                public_limit=10,
            )

        self.assertEqual(12, digest["sample"]["available_count"])
        self.assertEqual(10, digest["sample"]["sampled_count"])
        self.assertEqual(10, len(digest["public_sample"]))
        self.assertEqual("play-11", digest["public_sample"][0]["name"])
        self.assertNotEqual(
            [item["reference"] for item in digest["public_top"]],
            [item["reference"] for item in digest["public_sample"]],
        )

    def test_awareness_sha_is_stable_across_windows_but_changes_with_source_state(self) -> None:
        grouped = {
            "alpha": [
                {
                    "name": "one",
                    "visibility": "private",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "latest_version_created_at": "2026-07-01T00:00:00+00:00",
                }
            ]
        }
        first = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.start,
            end=self.end,
            public_limit=5,
        )
        later = build_digest(
            [Organization("alpha", "Alpha")],
            grouped,
            [],
            start=self.end,
            end=datetime(2026, 8, 5, tzinfo=timezone.utc),
            public_limit=5,
        )
        self.assertEqual(first["awareness_sha"], later["awareness_sha"])

        changed = {"alpha": [{**grouped["alpha"][0], "visibility": "public"}]}
        revised = build_digest(
            [Organization("alpha", "Alpha")],
            changed,
            [],
            start=self.end,
            end=datetime(2026, 8, 5, tzinfo=timezone.utc),
            public_limit=5,
        )
        self.assertNotEqual(first["awareness_sha"], revised["awareness_sha"])



class PublicBaselineTest(unittest.TestCase):
    """Every signed-in identity sees the public baseline, even with no organization."""

    def setUp(self) -> None:
        self.end = datetime(2026, 9, 2, tzinfo=timezone.utc)
        self.baseline_play = {
            "name": "hello",
            "visibility": "public",
            "status": "released",
            "created_at": "2026-06-01T00:00:00+00:00",
            "latest_version_created_at": "2026-06-01T00:00:00+00:00",
            "description": "Say hello.",
        }

    def _stats(self, grouped, **_):
        plays = [
            {
                "owner": owner,
                "name": play["name"],
                "visibility": "public",
                "download_count": 3,
                "install_count": 1,
                "owner_kind": "org",
                "description": play.get("description", ""),
                "reference": f"{owner}/{play['name']}",
            }
            for owner, plays in sorted(grouped.items())
            for play in plays
            if play.get("visibility") == "public"
        ]
        return PublicStatsBatch(
            plays=plays,
            errors=[],
            candidate_count=len(plays),
            omitted_count=0,
            elapsed_ms=1.0,
            workers=1,
        )

    def test_merge_adds_baseline_only_for_non_member_organizations(self) -> None:
        grouped = {"modiqo": [{"name": "internal", "visibility": "private"}]}
        baseline = {
            "modiqo": [self.baseline_play],
            "community": [self.baseline_play, {"name": "secret", "visibility": "private"}],
        }
        merged, contributed = merge_public_baseline(grouped, baseline)
        self.assertEqual(["community"], contributed)
        self.assertEqual(["internal"], [flow["name"] for flow in merged["modiqo"]])
        self.assertEqual(["hello"], [flow["name"] for flow in merged["community"]])
        self.assertEqual(grouped, {"modiqo": [{"name": "internal", "visibility": "private"}]})

    def test_zero_organization_identity_counts_baseline_plays(self) -> None:
        baseline_requests = []

        def load_baseline(authorized, **_):
            baseline_requests.append(set(authorized))
            return {"modiqo": [self.baseline_play]}

        with patch("play.digest.load_authorized_flows", return_value={}), patch(
            "play.digest.load_public_baseline_flows", side_effect=load_baseline
        ), patch("play.digest.load_registry_flow_infos") as infos, patch(
            "play.digest.inspect_references"
        ) as inspections, patch(
            "play.digest.fetch_authorized_public_stats", side_effect=self._stats
        ):
            infos.return_value.flows = []
            infos.return_value.errors = []
            infos.return_value.omitted_count = 0
            inspections.return_value.flows = []
            inspections.return_value.errors = []
            inspections.return_value.omitted_count = 0
            digest = collect_digest(days=7, organizations=[], end=self.end)

        self.assertEqual([set()], baseline_requests)
        self.assertEqual(1, digest["ranking"]["eligible_count"])
        self.assertEqual(1, digest["sample"]["available_count"])
        self.assertEqual(["modiqo/hello"], [item["reference"] for item in digest["public_sample"]])
        self.assertEqual(["modiqo"], digest["baseline"]["organizations"])
        self.assertEqual(
            "authorized_organizations_and_public_baseline", digest["ranking"]["scope"]
        )
        self.assertIn("public_baseline", digest["sources"])
        self.assertEqual([], digest["organizations"])
        markdown = render_markdown(digest)
        self.assertIn("**1 runnable public Play** visible to you", markdown)
        self.assertIn("- **hello** — Say hello.", markdown)
        self.assertIn("and the public `modiqo` baseline", markdown)
        self.assertTrue(supports_play_discovery(digest))

    def test_baseline_member_is_not_double_counted(self) -> None:
        member_catalog = {
            "modiqo": [
                self.baseline_play,
                {
                    "name": "internal",
                    "visibility": "private",
                    "created_at": "2026-06-01T00:00:00+00:00",
                    "latest_version_created_at": "2026-06-01T00:00:00+00:00",
                },
            ]
        }
        with patch("play.digest.load_authorized_flows", return_value=member_catalog), patch(
            "play.digest.load_public_baseline_flows", return_value={}
        ) as load_baseline, patch("play.digest.load_registry_flow_infos") as infos, patch(
            "play.digest.inspect_references"
        ) as inspections, patch(
            "play.digest.fetch_authorized_public_stats", side_effect=self._stats
        ):
            infos.return_value.flows = []
            infos.return_value.errors = []
            infos.return_value.omitted_count = 0
            inspections.return_value.flows = []
            inspections.return_value.errors = []
            inspections.return_value.omitted_count = 0
            digest = collect_digest(
                days=7, organizations=[Organization("modiqo", "Modiqo")], end=self.end
            )

        load_baseline.assert_called_once_with({"modiqo"})
        self.assertEqual(1, digest["ranking"]["eligible_count"])
        self.assertEqual([], digest["baseline"]["organizations"])
        self.assertEqual("authorized_organizations", digest["ranking"]["scope"])
        self.assertNotIn("public_baseline", digest["sources"])
        self.assertNotIn("baseline", render_markdown(digest))

    def test_caller_supplied_baseline_skips_live_baseline_read(self) -> None:
        with patch("play.digest.load_public_baseline_flows") as load_baseline, patch(
            "play.digest.load_registry_flow_infos"
        ) as infos, patch("play.digest.inspect_references") as inspections, patch(
            "play.digest.fetch_authorized_public_stats", side_effect=self._stats
        ):
            infos.return_value.flows = []
            infos.return_value.errors = []
            infos.return_value.omitted_count = 0
            inspections.return_value.flows = []
            inspections.return_value.errors = []
            inspections.return_value.omitted_count = 0
            digest = collect_digest(
                days=7,
                organizations=[],
                grouped_flows={},
                baseline_flows={"modiqo": [self.baseline_play]},
                end=self.end,
            )

        load_baseline.assert_not_called()
        self.assertEqual(1, digest["ranking"]["eligible_count"])
        self.assertEqual(["modiqo"], digest["baseline"]["organizations"])

    def test_untimestamped_baseline_card_counts_without_failing_updates(self) -> None:
        minimal = {"name": "starter", "visibility": "public", "status": "released"}
        with patch("play.digest.load_registry_flow_infos") as infos, patch(
            "play.digest.inspect_references"
        ) as inspections, patch(
            "play.digest.fetch_authorized_public_stats", side_effect=self._stats
        ):
            infos.return_value.flows = []
            infos.return_value.errors = []
            infos.return_value.omitted_count = 0
            inspections.return_value.flows = []
            inspections.return_value.errors = []
            inspections.return_value.omitted_count = 0
            digest = collect_digest(
                days=7,
                organizations=[],
                grouped_flows={},
                baseline_flows={"modiqo": [minimal]},
                end=self.end,
            )

        self.assertEqual(1, digest["ranking"]["eligible_count"])
        self.assertEqual([], digest["org_updates"]["new"])
        self.assertTrue(digest["org_updates"]["revised_complete"])
        self.assertIsNone(digest["public_sample"][0]["recent_at"])

    def test_authorized_card_without_timestamp_still_fails_closed(self) -> None:
        minimal = {"name": "starter", "visibility": "public", "status": "released"}
        with patch("play.digest.load_registry_flow_infos"), patch(
            "play.digest.inspect_references"
        ), patch("play.digest.fetch_authorized_public_stats", side_effect=self._stats):
            with self.assertRaises(TimeWindowError):
                collect_digest(
                    days=7,
                    organizations=[Organization("acme", "Acme")],
                    grouped_flows={"acme": [minimal]},
                    baseline_flows={},
                    end=self.end,
                )

    def test_baseline_changes_the_awareness_fingerprint(self) -> None:
        start = datetime(2026, 8, 26, tzinfo=timezone.utc)
        without = build_digest([], {}, [], start=start, end=self.end, public_limit=10)
        with_baseline = build_digest(
            [],
            {"modiqo": [self.baseline_play]},
            [],
            start=start,
            end=self.end,
            public_limit=10,
            baseline_organizations=["modiqo"],
        )
        self.assertNotEqual(without["awareness_sha"], with_baseline["awareness_sha"])


if __name__ == "__main__":
    unittest.main()
