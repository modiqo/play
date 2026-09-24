"""The passive hook only suggests Worker-confirmed published direct matches."""

import io
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from play import intercept, search
from play.search import SearchError


def result(status="direct", mode="judged", complete=True):
    return {
        "results": [
            {"relevance_status": status, "exact_reference": "team/audit-dns@1.2.3"}
        ],
        "complete": complete,
        "source_health": {"mode": mode},
    }


class InterceptTest(unittest.TestCase):
    def test_direct_match_suggests_pinned_version_without_execution(self):
        with mock.patch.object(
            search, "search_published", return_value=result()
        ) as call:
            line = intercept.intercept_prompt("Check DNS without changing any records")
        call.assert_called_once_with(
            "Check DNS without changing any records", limit=3, timeout_seconds=3.0
        )
        assert line is not None
        self.assertIn("team/audit-dns@1.2.3", line)
        self.assertIn("Do not enter the Play state", line)
        self.assertIn("non-blocking", line)

    def test_partial_uncertain_degraded_and_empty_stay_quiet(self):
        cases = [
            result("partial"),
            result("uncertain"),
            result("unverified"),
            result(mode="degraded"),
            {"results": [], "source_health": {"mode": "judged"}},
        ]
        for payload in cases:
            with (
                self.subTest(payload=payload),
                mock.patch.object(search, "search_published", return_value=payload),
            ):
                self.assertIsNone(intercept.intercept_prompt("Delete DNS records"))

    def test_valid_direct_match_survives_unrelated_group_truncation(self):
        with mock.patch.object(
            search, "search_published", return_value=result(complete=False)
        ):
            self.assertIsNotNone(intercept.intercept_prompt("Check DNS records"))

    def test_no_network_for_discussion_explicit_commands_or_hello(self):
        prompts = [
            "Should we audit DNS records?",
            "How do I audit DNS records?",
            "Could you explain DNS records?",
            "$play audit DNS",
            "/play audit DNS",
            "!check DNS records",
            "Run hello",
            "hi",
            "",
        ]
        with mock.patch.object(search, "search_published") as call:
            for prompt in prompts:
                self.assertIsNone(intercept.intercept_prompt(prompt), prompt)
            call.assert_not_called()

    def test_timeout_old_rote_and_identity_failure_stay_silent(self):
        for error in [
            SearchError("timeout"),
            SearchError("unknown source semantic"),
            SearchError("sign in"),
            OSError("missing binary"),
        ]:
            with mock.patch.object(search, "search_published", side_effect=error):
                self.assertIsNone(intercept.intercept_prompt("Check DNS records"))

    def test_native_hook_envelope_and_invalid_input(self):
        with (
            mock.patch(
                "sys.stdin", io.StringIO(json.dumps({"prompt": "Check DNS records"}))
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            mock.patch.object(search, "search_published", return_value=result()),
        ):
            self.assertEqual(0, intercept.main(["prompt"]))
            payload = json.loads(output.getvalue())
        self.assertTrue(payload["suppressOutput"])
        self.assertEqual(
            "UserPromptSubmit", payload["hookSpecificOutput"]["hookEventName"]
        )
        for raw in ["not json", "[]", "{}"]:
            with (
                mock.patch("sys.stdin", io.StringIO(raw)),
                mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                self.assertEqual(0, intercept.main(["prompt"]))
                self.assertEqual("", output.getvalue())

    def test_old_stop_hooks_remain_inert(self):
        with (
            mock.patch("sys.stdin", io.StringIO("{}")),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            mock.patch.object(search, "search_published") as call,
        ):
            self.assertEqual(0, intercept.main(["settle-nudge"]))
            self.assertEqual("", output.getvalue())
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
