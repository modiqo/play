"""Published-only discovery contract and false-positive regressions."""

import io
import pathlib
import os
import tempfile
import sys
import unittest
from unittest import mock
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from play import search


def candidate(
    status="direct", owner="alice", name="audit-dns", visibility="public"
) -> dict[str, Any]:
    ref = f"{owner}/{name}@1.2.3"
    return dict(
        reference=ref,
        url="https://play.modiqo.ai/" + ref,
        name=name,
        description="Inspect DNS records without changing them",
        owner_slug=owner,
        version="1.2.3",
        visibility=visibility,
        relevance=dict(status=status, probability=0.93),
    )


def group(kind="community", owner=None, matches=None, uncertain=None) -> dict[str, Any]:
    return dict(
        kind=kind,
        id=owner or kind,
        label=owner or "Community",
        owner_slug=owner,
        retrieval=dict(status="ok", truncated=False, errors=[]),
        judgment_complete=True,
        display_truncated=False,
        matches=matches or [],
        uncertain=uncertain or [],
    )


def response(groups=None) -> dict[str, Any]:
    return dict(
        schema="modiqo.play-search.v1",
        registry="production",
        mode="judged",
        complete=True,
        policy_version="test-v1",
        omitted_groups=[],
        groups=groups if groups is not None else [group(matches=[candidate()])],
    )


class SearchTest(unittest.TestCase):
    def run_search(self, body=None, **kwargs):
        with mock.patch.object(
            search, "request_search", return_value=body or response()
        ) as call:
            result = search.search_published(
                "Audit DNS without changing records", **kwargs
            )
        return result, call

    def test_only_shared_transport_with_accessible_scope(self):
        result, call = self.run_search()
        call.assert_called_once_with(
            "Audit DNS without changing records", public=False, org=None,
            limit=5, timeout_seconds=25.0,
        )
        self.assertTrue(result["complete"])
        self.assertEqual(["shared_worker"], result["sources"])
        hit = result["results"][0]
        self.assertEqual("jev", hit["match_basis"])
        self.assertEqual("full", hit["match_classification"])
        self.assertEqual("alice/audit-dns@1.2.3", hit["reference"])
        self.assertEqual(
            "rote play inspect alice/audit-dns@1.2.3 --json", hit["inspect_command"]
        )
        self.assertEqual("inspect_required", hit["execution_resolution"])
        self.assertEqual(hit["reference"], result["play_choices"][0]["reference"])

    def test_native_rote_envelope(self):
        result, _ = self.run_search({"schema": 1, "data": {"result": response()}})
        self.assertEqual(1, len(result["results"]))

    def test_public_and_org_scopes(self):
        _, call = self.run_search(public=True)
        self.assertTrue(call.call_args.kwargs["public"])
        body = response(
            [
                group(
                    "organization",
                    "team",
                    [candidate(owner="team", visibility="private")],
                )
            ]
        )
        result, call = self.run_search(body, org="team")
        self.assertEqual("team", call.call_args.kwargs["org"])
        self.assertEqual("team", result["results"][0]["ownership"])
        with self.assertRaises(search.SearchError):
            self.run_search(public=True, org="team")

    def test_preserves_negation_quotes_and_redacts_parameter_values(self):
        query = search.relevance_query(
            'Audit DNS "without changing anything" at https://example.com for a@example.com ~/private.txt token=abc123'
        )
        self.assertIn('"without changing anything"', query)
        for secret in ["example.com", "private.txt", "abc123"]:
            self.assertNotIn(secret, query)
        self.assertIn("[credential]", query)
        self.assertIn("[argument]", query)

    def test_original_wording_wins_over_paraphrase(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "play-search",
                    "repair DNS",
                    "--also",
                    "Audit DNS without changing anything",
                    "--json",
                ],
            ),
            mock.patch.object(
                search, "search_request", return_value={"ok": True}
            ) as call,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(0, search.main())
        self.assertEqual("Audit DNS without changing anything", call.call_args.args[0])

    def test_no_keyword_or_cached_fallback_on_rejection(self):
        result, call = self.run_search(response([group()]))
        self.assertEqual([], result["results"])
        self.assertTrue(result["complete"])
        self.assertEqual(1, call.call_count)

    def test_uncertain_and_partial_never_become_full(self):
        body = response(
            [
                group(
                    matches=[candidate("partial")],
                    uncertain=[
                        candidate("uncertain", name="other"),
                        candidate("unverified", name="third"),
                    ],
                )
            ]
        )
        result, _ = self.run_search(body)
        self.assertEqual(
            ["partial", "uncertain", "uncertain"],
            [r["match_classification"] for r in result["results"]],
        )
        self.assertTrue(all(r["uncovered_terms"] for r in result["results"]))
        text = search.render_markdown(
            "", result["query"], result["results"], result["source_health"]
        )
        self.assertIn("Possible matches", text)

    def test_unrelated_judgment_never_outranks_partial(self):
        # Production shape: an uncertain row the model called unrelated has a
        # higher label probability than one it called partial.
        mine = candidate("uncertain", owner="me", name="my-issues")
        mine["relevance"] = dict(status="uncertain", choice="unrelated", probability=0.77)
        theirs = candidate("uncertain", name="stale-prs")
        theirs["relevance"] = dict(status="uncertain", choice="partial", probability=0.70)
        body = response(
            [group("personal", "me", uncertain=[mine]), group(uncertain=[theirs])]
        )
        result, _ = self.run_search(body)
        self.assertEqual(
            ["alice/stale-prs@1.2.3", "me/my-issues@1.2.3"], result["result_refs"]
        )
        self.assertEqual([0.70, 0.0], [r["coverage"] for r in result["results"]])

    def test_incompleteness_survives_each_worker_failure_signal(self):
        for change in [
            "complete",
            "mode",
            "omitted",
            "judgment",
            "retrieval",
            "truncated",
            "display",
        ]:
            with self.subTest(change=change):
                body = response()
                if change == "complete":
                    body["complete"] = False
                if change == "mode":
                    body["mode"] = "degraded"
                if change == "omitted":
                    body["omitted_groups"] = [{"owner_slug": "team"}]
                if change == "judgment":
                    body["groups"][0]["judgment_complete"] = False
                if change == "retrieval":
                    body["groups"][0]["retrieval"]["status"] = "unavailable"
                if change == "truncated":
                    body["groups"][0]["retrieval"]["truncated"] = True
                if change == "display":
                    body["groups"][0]["display_truncated"] = True
                result, _ = self.run_search(body)
                self.assertFalse(result["complete"])
                self.assertFalse(result["source_health"]["complete"])
                self.assertEqual(1, len(result["results"]))

    def test_scope_identity_and_contract_fail_closed(self):
        bodies = []
        for path, value in [
            (["registry"], "custom"),
            (["mode"], []),
            (["groups", 0, "id"], []),
            (["groups", 0, "matches", 0, "url"], "https://evil.test/"),
            (["groups", 0, "matches", 0, "reference"], "local-draft"),
            (["groups", 0, "matches", 0, "visibility"], "private"),
            (["groups", 0, "matches", 0, "relevance", "status"], "rejected"),
            (["groups", 0, "matches", 0, "version"], "9.0.0"),
        ]:
            body = response()
            target = body
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            bodies.append(body)
        bodies += [
            response([]),
            {"schema": "old-search"},
            response([group(matches=[candidate(), candidate()])]),
        ]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(search.SearchError):
                self.run_search(body)
        with self.assertRaises(search.SearchError):
            self.run_search(
                response([group(), group("personal", "alice")]), public=True
            )
        with self.assertRaises(search.SearchError):
            self.run_search(
                response(
                    [group("organization", "team", [candidate(owner="outsider")])]
                ),
                org="team",
            )

    def test_transport_failure_is_not_empty_success(self):
        with mock.patch.object(
            search, "request_search", side_effect=search.SearchError("timed out")
        ) as call:
            with self.assertRaises(search.SearchError):
                search.search_published("audit DNS")
            self.assertEqual(1, call.call_count)

    def test_query_bounds_never_silently_truncate_constraints(self):
        for query in ["", "ab", "x" * 401]:
            with self.assertRaises(search.SearchError):
                search.relevance_query(query)
        for limit in [0, 13]:
            with self.assertRaises(search.SearchError):
                self.run_search(limit=limit)

    def test_decomposition_uses_same_worker_and_retains_whole_constraints(self):
        with (
            mock.patch.object(
                search, "separable_outcomes", return_value=["audit DNS", "send report"]
            ),
            mock.patch.object(search, "request_search", return_value=response()) as call,
        ):
            result = search.search_request(
                "Audit DNS without changing records and send report", decompose=True
            )
        self.assertEqual(3, call.call_count)
        for invocation in call.call_args_list:
            self.assertIn("without changing records", invocation.args[0])
            self.assertFalse(invocation.kwargs["public"])
        self.assertEqual(2, len(result["sub_outcomes"]))

    def test_unpublished_files_and_cached_names_never_enter_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / "audit-dns").mkdir()
            (root / "audit-dns" / "main.ts").write_text(
                "name: audit-dns; description: audit DNS without changes"
            )
            (root / "catalog.json").write_text('{"plays":[{"name":"audit-dns"}]}')
            with mock.patch.dict(
                os.environ,
                {
                    "ROTE_HOME": temp,
                    "PLAY_INTERCEPT_FLOWS_ROOT": temp,
                    "PLAY_INBOX_CACHE_PATH": str(root / "catalog.json"),
                },
            ):
                result, call = self.run_search(response([group()]))
            self.assertEqual([], result["results"])
            self.assertEqual(1, call.call_count)

    def test_audit_corpus_uses_judged_published_versions_and_reports_failure(self):
        from play.audit import corpus

        body = response(
            [
                group(
                    matches=[candidate()],
                    uncertain=[candidate("unverified", name="unknown")],
                )
            ]
        )
        with mock.patch.object(search, "request_search", return_value=body) as call:
            self.assertEqual(
                ["alice/audit-dns@1.2.3"], corpus.registry_references(["audit DNS"])
            )
        self.assertFalse(call.call_args.kwargs["public"])
        with (
            mock.patch.object(
                corpus,
                "search_published",
                side_effect=search.SearchError("unavailable"),
            ),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(1, corpus.main(["refs", "--query", "audit DNS"]))

    def test_subquery_failure_preserves_primary_matches_and_marks_incomplete(self):
        with (
            mock.patch.object(
                search, "separable_outcomes", return_value=["audit DNS", "send report"]
            ),
            mock.patch.object(
                search,
                "request_search",
                side_effect=[response(), search.SearchError("timeout"), response()],
            ),
        ):
            result = search.search_request("Audit DNS and send report", decompose=True)
        self.assertFalse(result["complete"])
        self.assertEqual(1, len(result["results"]))
        self.assertFalse(result["sub_outcomes"][0]["complete"])

    def test_incomplete_no_results_cannot_claim_absence(self):
        text = search.render_markdown("", "audit DNS", [], {"complete": False})
        self.assertIn("Search is incomplete", text)
        self.assertNotIn("No matching published Plays found", text)


if __name__ == "__main__":
    unittest.main()
