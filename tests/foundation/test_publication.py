from __future__ import annotations

import unittest

from scripts.lib.play.publication import (
    PublicationPresentationError,
    build_publication_presentation,
)


class PublicationPresentationTest(unittest.TestCase):
    def payload(self, *, visibility: str = "public") -> dict:
        return {
            "title": "Modiqo Pricing Grid",
            "description": "Compare pricing and packaging choices for developer SaaS.",
            "canonical_reference": "daily-chores/modiqo-pricing-grid",
            "version": "0.0.1",
            "visibility": visibility,
            "owner": "daily-chores",
            "content_hash": "d79b9431aac7",
            "play_uri": (
                "https://play.modiqo.ai/daily-chores/modiqo-pricing-grid@0.0.1"
            ),
            "install_uri": (
                "https://play.modiqo.ai/install?play=daily-chores/modiqo-pricing-grid@0.0.1"
                if visibility == "public"
                else None
            ),
            "credential_status": "verified" if visibility == "public" else "not_required",
            "smoke_status": "verified" if visibility == "public" else "not_required",
            "smoke_exact_reference": (
                "https://play.modiqo.ai/daily-chores/modiqo-pricing-grid@0.0.1"
                if visibility == "public"
                else None
            ),
            "smoke_ns": 12_500_000 if visibility == "public" else None,
        }

    def test_public_readout_contains_clickable_links_and_paste_ready_copy(self) -> None:
        result = build_publication_presentation(self.payload())

        self.assertIn("[Modiqo Pricing Grid — Compare pricing", result["markdown"])
        self.assertIn("Paste for X", result["markdown"])
        self.assertIn("Paste for LinkedIn", result["markdown"])
        self.assertIn(result["play_uri"], result["share_copy"]["x"])
        self.assertIn(result["play_uri"], result["share_copy"]["linkedin"])
        self.assertIn(result["install_uri"], result["share_copy"]["linkedin"])
        self.assertLessEqual(len(result["share_copy"]["x"]), 280)
        self.assertEqual(
            "daily-chores/modiqo-pricing-grid@0.0.1",
            result["canonical_reference"],
        )
        self.assertEqual(64, len(result["presentation_ref"]))

    def test_long_x_copy_is_truncated_without_dropping_the_uri(self) -> None:
        payload = self.payload()
        payload["description"] = "Long description " * 100

        result = build_publication_presentation(payload)

        self.assertLessEqual(len(result["share_copy"]["x"]), 280)
        self.assertTrue(result["share_copy"]["x"].endswith(result["play_uri"]))
        self.assertIn("…", result["share_copy"]["x"])

    def test_accepts_the_controller_context_shape(self) -> None:
        payload = self.payload()
        context = {
            "publication": {
                "title": payload["title"],
                "description": payload["description"],
                "canonical_reference": payload["canonical_reference"],
                "visibility": payload["visibility"],
                "owner": payload["owner"],
                "content_hash": payload["content_hash"],
                "uri": payload["play_uri"],
                "install_uri": payload["install_uri"],
            },
            "play": {"version": payload["version"]},
            "publication_validation": {
                "credential_status": payload["credential_status"],
                "smoke_status": payload["smoke_status"],
                "smoke_exact_reference": payload["smoke_exact_reference"],
                "smoke_ns": payload["smoke_ns"],
            },
        }

        result = build_publication_presentation(context)

        self.assertEqual(payload["play_uri"], result["play_uri"])
        self.assertEqual(payload["install_uri"], result["install_uri"])

    def test_public_readout_requires_credential_and_smoke_verification(self) -> None:
        payload = self.payload()
        payload["smoke_status"] = "failed"
        with self.assertRaisesRegex(PublicationPresentationError, "canonical smoke run"):
            build_publication_presentation(payload)

        payload = self.payload()
        payload["credential_status"] = "failed"
        with self.assertRaisesRegex(PublicationPresentationError, "credential contracts"):
            build_publication_presentation(payload)

        payload = self.payload()
        payload["smoke_ns"] = None
        with self.assertRaisesRegex(PublicationPresentationError, "smoke latency"):
            build_publication_presentation(payload)

    def test_public_readout_requires_registry_returned_https_uris(self) -> None:
        payload = self.payload()
        payload["play_uri"] = None
        with self.assertRaisesRegex(PublicationPresentationError, "play_uri"):
            build_publication_presentation(payload)

        payload = self.payload()
        payload["install_uri"] = "http://play.modiqo.ai/install"
        with self.assertRaisesRegex(PublicationPresentationError, "absolute HTTPS"):
            build_publication_presentation(payload)

    def test_private_readout_does_not_create_public_social_copy(self) -> None:
        result = build_publication_presentation(self.payload(visibility="private"))

        self.assertIsNotNone(result["share_copy"]["team"])
        self.assertIsNone(result["share_copy"]["x"])
        self.assertIsNone(result["share_copy"]["linkedin"])
        self.assertIn(result["play_uri"], result["share_copy"]["team"])
        self.assertIn("Ask me to add you", result["share_copy"]["team"])
        self.assertIn("Paste to your team", result["markdown"])
        self.assertNotIn("Paste for X", result["markdown"])
        self.assertIn("Private Play page:", result["markdown"])


if __name__ == "__main__":
    unittest.main()
