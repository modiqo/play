from __future__ import annotations

import io
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play import tag_hints


FRONTMATTER = """#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: retrieve-recent-emails
 * description: Retrieves recent Gmail messages matching a Gmail search query.
 * metadata:
 *   version: 0.1.6
 *   discoverability:
 *     tags:
 *     - job-email-review
 *     - tool-gmail
 * parameters: []
 * ---
 */
export default async function main() {}
"""


class TagHintsTest(unittest.TestCase):
    def test_reports_outcome_words_the_card_does_not_cover(self) -> None:
        report = tag_hints.suggest_tags(
            ["summarize last email"],
            "retrieve-recent-emails",
            "Retrieves recent Gmail messages matching a Gmail search query.",
            ["job-email-review"],
        )
        self.assertEqual(["summarize", "last", "email"], report["outcome_terms"])
        self.assertEqual(["summarize", "last"], report["suggested_tags"])
        self.assertFalse(report["discoverable_by_request"])

    def test_covered_request_suggests_nothing(self) -> None:
        report = tag_hints.suggest_tags(
            ["retrieve recent emails for https://example.com"],
            "retrieve-recent-emails",
            "Retrieves recent Gmail messages.",
            [],
        )
        self.assertEqual([], report["suggested_tags"])
        self.assertTrue(report["discoverable_by_request"])
        self.assertIn("already covers", tag_hints.render_markdown(report))

    def test_reads_the_first_frontmatter_document_from_main_ts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            play = pathlib.Path(temporary) / "main.ts"
            play.write_text(FRONTMATTER, encoding="utf-8")
            card = tag_hints.read_card(play)
            self.assertEqual("retrieve-recent-emails", card["name"])
            self.assertEqual(["job-email-review", "tool-gmail"], card["tags"])

            output = io.StringIO()
            with redirect_stdout(output):
                code = tag_hints.main(
                    ["--request", "summarize last email", "--play", str(play)]
                )
            self.assertEqual(0, code)
            self.assertIn("- summarize", output.getvalue())
            self.assertIn("- last", output.getvalue())
            self.assertNotIn("- email", output.getvalue())

    def test_missing_frontmatter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            play = pathlib.Path(temporary) / "main.ts"
            play.write_text("export default 1;", encoding="utf-8")
            with self.assertRaises(tag_hints.TagHintError):
                tag_hints.read_card(play)


if __name__ == "__main__":
    unittest.main()
