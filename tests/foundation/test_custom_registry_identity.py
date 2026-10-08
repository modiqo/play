"""Custom search routing must not change a published Play's registry identity."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.lib.play import onboarding, play_run, publication, public_trends
from scripts.lib.play.audit import cli as audit_cli
from scripts.lib.play.commands import CommandError


class CustomRegistryIdentityTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        config = Path(home.name) / "registry/config.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"url": "http://127.0.0.1:54321"}))
        env = patch.dict(os.environ, {
            "ROTE_HOME": home.name,
            "ROTE_REGISTRY_ENV": "",
            "PLAY_SEARCH_ENDPOINT": "http://127.0.0.1:8765/v1/search",
        })
        env.start()
        self.addCleanup(env.stop)
        self.uri = "https://play.test.modiqo.ai/alice/audit-dns@1.2.3"

    def test_native_invocation_and_latest_selector_retain_test_origin(self):
        self.assertEqual(self.uri, onboarding.canonical_play_uri(self.uri))
        self.assertIsNone(onboarding.canonical_play_uri(self.uri.replace("play.test.", "play.")))
        classified = onboarding.classify_invocation("$play " + self.uri)
        self.assertEqual(self.uri, classified["play_uri"])
        self.assertEqual("https://play.test.modiqo.ai/alice/audit-dns", play_run._latest_execution_target(self.uri))
        self.assertEqual("1.2.3", audit_cli.requested_version(self.uri))
        self.assertEqual("https://play.test.modiqo.ai/modiqo/hello", onboarding.classify_invocation("$play run hello")["play_uri"])

    def test_website_only_reads_are_honestly_unsupported(self):
        with self.assertRaisesRegex(onboarding.OnboardingError, "unsupported"), patch.object(onboarding.subprocess, "run") as run:
            onboarding.fetch_public_card({"onboarding": {"play_uri": self.uri}})
        run.assert_not_called()
        with self.assertRaisesRegex(CommandError, "unsupported"):
            public_trends._card_url("alice/audit-dns@1.2.3")

    def test_missing_local_endpoint_blocks_website_reads_before_network(self):
        with patch.dict(os.environ, {"PLAY_SEARCH_ENDPOINT": ""}):
            with self.assertRaisesRegex(onboarding.OnboardingError, "explicit search endpoint"), patch.object(onboarding.subprocess, "run") as run:
                onboarding.fetch_public_card({"onboarding": {"play_uri": self.uri}})
            run.assert_not_called()
            with self.assertRaisesRegex(CommandError, "explicit search endpoint"):
                public_trends._card_url("alice/audit-dns@1.2.3")

    def test_creator_publication_requires_configured_exact_uri(self):
        payload = {
            "title": "Audit DNS", "description": "Read DNS records",
            "canonical_reference": "alice/audit-dns", "version": "1.2.3",
            "visibility": "private", "owner": "alice", "content_hash": "actual-readback-hash",
            "play_uri": self.uri, "install_uri": None,
            "credential_status": "not_required", "smoke_status": "not_required",
        }
        self.assertEqual(self.uri, publication.build_publication_presentation(payload)["play_uri"])
        payload["play_uri"] = self.uri.replace("play.test.", "play.")
        with self.assertRaisesRegex(publication.PublicationPresentationError, "configured registry"):
            publication.build_publication_presentation(payload)
