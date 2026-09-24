"""Newsletter output stays bounded, public, and honest about first publications."""

import io
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from play.digest import newsletter_sections, newsletter_choices, render_markdown
from play import inbox_cache


def row(owner, name, created: str | None = "2026-09-20T00:00:00Z", **kwargs):
    return dict(
        reference=f"{owner}/{name}",
        name=name,
        visibility="public",
        created_at=created,
        description="This long description must never appear",
        **kwargs,
    )


def digest(catalog):
    value = {
        "window": {"start": "2026-09-16T00:00:00Z", "end": "2026-09-23T00:00:00Z"},
        "memory": {},
        "org_updates": {"new": [], "revised": []},
    }
    value["newsletter"] = newsletter_sections(value, catalog)
    return value


class NewsletterTest(unittest.TestCase):
    def test_two_title_sections_are_bounded_and_deduplicated(self):
        catalog = [
            row("modiqo", f"curated-{i}", "2026-08-01T00:00:00Z") for i in range(50)
        ]
        catalog += [row("alice", f"new-{i}") for i in range(40)]
        value = digest(catalog)
        text = render_markdown(value)
        self.assertEqual(10, len(newsletter_choices(value)))
        self.assertEqual(10, sum(line.startswith("- [") for line in text.splitlines()))
        self.assertLess(len(text), 1400)
        self.assertNotIn("long description", text)
        self.assertNotIn("run hello", text)
        self.assertNotIn("download", text)
        self.assertIn("Browse community Plays", text)

    def test_new_modiqo_play_appears_once_in_new_community(self):
        value = digest([row("modiqo", "new-play"), row("modiqo", "new-play")])
        self.assertEqual(1, len(newsletter_choices(value)))
        self.assertEqual("community", newsletter_choices(value)[0]["section"])

    def test_private_drafts_deleted_and_revised_are_not_new(self):
        private = row("modiqo", "private")
        private["visibility"] = "private"
        value = digest(
            [
                private,
                row("alice", "draft", status="draft"),
                row("alice", "deleted", deleted_at="now"),
                row(
                    "alice",
                    "revised",
                    "2026-08-01T00:00:00Z",
                    latest_version_created_at="2026-09-21T00:00:00Z",
                ),
                row("alice", "missing-date", None),
                row("alice", "future", "2026-10-01T00:00:00Z"),
            ]
        )
        self.assertEqual([], newsletter_choices(value))

    def test_repeat_snapshot_does_not_reannounce_new_plays(self):
        value = digest(
            [row("alice", "new"), row("modiqo", "hello", "2026-08-01T00:00:00Z")]
        )
        value["memory"] = {"status": "unchanged"}
        text = render_markdown(value)
        self.assertIn("No new additions since your last check", text)
        self.assertNotIn("alice/new", text)
        self.assertIn("modiqo/hello", text)

    def test_checkpoint_excludes_older_cached_announcements(self):
        value = digest(
            [
                row("alice", "old", "2026-09-19T00:00:00Z"),
                row("alice", "fresh", "2026-09-22T00:00:00Z"),
            ]
        )
        value["memory"] = {"status": "changed", "since": "2026-09-21T00:00:00Z"}
        self.assertEqual(
            ["alice/fresh"], [r["reference"] for r in newsletter_choices(value)]
        )

    def test_offline_snapshot_keeps_modiqo_titles_but_does_not_claim_live_news(self):
        value = digest([row("modiqo", "hello"), row("alice", "new")])
        value["availability"] = {"status": "public_cache_only"}
        text = render_markdown(value)
        self.assertIn("modiqo/hello", text)
        self.assertNotIn("alice/new", text)
        self.assertIn("New additions unavailable", text)
        self.assertIn("may be out of date", text)

    def test_titles_escape_markdown_and_references_cannot_inject_links(self):
        value = digest(
            [
                row("modiqo", "hello", title="[Surprise](evil)"),
                dict(row("modiqo", "bad"), reference="modiqo/bad)\nattack"),
            ]
        )
        text = render_markdown(value)
        self.assertNotIn("[Surprise](evil)", text)
        self.assertNotIn("attack", text)

    def test_cached_details_rerenders_old_verbose_markdown_without_network(self):
        catalog = [row("modiqo", "hello", "2026-08-01T00:00:00Z")]
        cache = {
            "digest": digest(catalog),
            "public_catalog": catalog,
            "markdown": "OLD FULL CATALOG DUMP",
        }
        with (
            patch.object(inbox_cache, "read_cache", return_value=cache),
            patch.object(inbox_cache, "refresh_cache") as refresh,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertEqual(0, inbox_cache.main(["details"]))
            self.assertNotIn("OLD FULL CATALOG DUMP", output.getvalue())
            self.assertIn("modiqo/hello", output.getvalue())
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
