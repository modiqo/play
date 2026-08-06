from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.run_output import RunOutputError, build_detailed_output


def detailed_payload(**output_overrides):
    output = {
        "mode": "detailed",
        "detail": "full",
        "source": "rote_human_presentation",
        "format": "markdown",
        "primary": "## Customers\n\n- Alpha\n- Beta",
        "manifest": {
            "response_refs": ["@1", "@2"],
            "artifact_refs": ["artifact:report.csv"],
            "effects": ["read"],
        },
        "truncated": False,
        "full_output_ref": None,
    }
    output.update(output_overrides)
    return {
        "reference": "acme/customer-report",
        "version": "1.2.0",
        "output_policy": {
            "mode": "detailed",
            "preferred_presentation": "human",
            "max_inline_bytes": output.pop("max_inline_bytes", 200_000),
            "overflow": "artifact",
        },
        "output": output,
    }


class RunOutputTest(unittest.TestCase):
    def test_preserves_human_markdown_and_adds_run_details(self) -> None:
        result = build_detailed_output(detailed_payload())
        markdown = result["presentation_markdown"]

        self.assertTrue(result["complete"])
        self.assertEqual("detailed", result["mode"])
        self.assertIn("## Customers", markdown)
        self.assertIn("`acme/customer-report@1.2.0`", markdown)
        self.assertIn("`@1`, `@2`", markdown)
        self.assertEqual(64, len(result["presentation_sha256"]))

    def test_formats_flat_json_records_as_a_markdown_table(self) -> None:
        result = build_detailed_output(
            detailed_payload(
                source="rote_json_presentation",
                format="json",
                primary=[
                    {"name": "Alpha", "active": True},
                    {"name": "Beta", "active": False},
                ],
            )
        )
        markdown = result["presentation_markdown"]

        self.assertIn("| name | active |", markdown)
        self.assertIn("| Alpha | true |", markdown)
        self.assertIn("| Beta | false |", markdown)

    def test_rejects_summary_only_output(self) -> None:
        with self.assertRaisesRegex(RunOutputError, "summary-only"):
            build_detailed_output(detailed_payload(detail="summary"))

    def test_rejects_a_summary_output_policy(self) -> None:
        payload = detailed_payload()
        payload["output_policy"]["mode"] = "summary"
        with self.assertRaisesRegex(RunOutputError, "policy mode must be detailed"):
            build_detailed_output(payload)

    def test_rejects_compact_summary_source(self) -> None:
        with self.assertRaisesRegex(RunOutputError, "cannot prove full detail"):
            build_detailed_output(
                detailed_payload(source="rote_compact_summary", detail="full")
            )

    def test_truncated_output_requires_a_complete_reference(self) -> None:
        with self.assertRaisesRegex(RunOutputError, "requires full_output_ref"):
            build_detailed_output(detailed_payload(truncated=True))

    def test_oversized_output_fails_closed_without_complete_reference(self) -> None:
        with self.assertRaisesRegex(RunOutputError, "has no full_output_ref"):
            build_detailed_output(
                detailed_payload(primary="x" * 100, max_inline_bytes=20)
            )

    def test_oversized_output_uses_bounded_preview_and_complete_reference(self) -> None:
        result = build_detailed_output(
            detailed_payload(
                primary="é" * 100,
                max_inline_bytes=21,
                full_output_ref="artifact:full-output.md",
            )
        )

        self.assertTrue(result["truncated"])
        self.assertIn("complete result is preserved", result["presentation_markdown"])
        self.assertIn("`artifact:full-output.md`", result["presentation_markdown"])


if __name__ == "__main__":
    unittest.main()
