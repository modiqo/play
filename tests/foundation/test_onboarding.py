from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.onboarding import (
    OnboardingError,
    canonical_play_uri,
    classify_invocation,
    inspect_identity,
    normalize_card,
    probe_rote,
    render_card,
)


URI = "https://play.modiqo.ai/chetan/list-my-github-repos@0.0.2"


def public_card() -> dict:
    return {
        "schema": "rote.play.v1",
        "type": "play",
        "id": URI,
        "title": "List my GitHub repos",
        "name": "list-my-github-repos",
        "description": "List repositories for the authenticated GitHub user.",
        "reference": "chetan/list-my-github-repos@0.0.2",
        "version": "0.0.2",
        "visibility": "public",
        "actions": {
            "inspect": {"command": f"rote play inspect {URI}", "effect": "read-only"},
            "bootstrapAndRun": {
                "href": f"https://play.modiqo.ai/install?play={URI.split('/', 3)[-1]}",
                "requiresConsent": True,
            },
            "installCliOnly": {
                "href": "https://play.modiqo.ai/install",
                "requiresConsent": True,
            },
        },
        "parameters": [
            {
                "name": "per_page",
                "type": "string",
                "required": False,
                "default": "10",
                "description": "Number of repositories to return.",
            }
        ],
        "requirements": {
            "adapters": [
                {
                    "id": "github",
                    "displayName": "GitHub",
                    "requirement": "chetan/github@1.1.0",
                    "credentialDemand": {
                        "status": "required",
                        "requirements": [
                            {"name": "GITHUB_API_TOKEN", "protocol": "static"}
                        ],
                    },
                }
            ]
        },
        "effects": {"declaredWrites": [], "credentialsRemainLocal": True},
    }


class InvocationClassificationTest(unittest.TestCase):
    def test_empty_play_aliases_enter_greeting(self) -> None:
        for value in ("$play", "/play", "  $PLAY  "):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("greeting", result["invocation_kind"])
                self.assertIsNone(result["play_uri"])

    def test_prefixed_or_bare_canonical_uri_enters_uri_onboarding(self) -> None:
        for value in (URI, f"$play {URI}", f"/play {URI}"):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("play_uri", result["invocation_kind"])
                self.assertEqual(URI, result["play_uri"])

    def test_noncanonical_hosts_and_nonempty_requests_remain_ordinary(self) -> None:
        for value in (
            "$play find recent emails",
            "/play create a report",
            "https://example.com/chetan/report@1.0.0",
            "file:///etc/passwd",
        ):
            with self.subTest(value=value):
                self.assertEqual("ordinary", classify_invocation(value)["invocation_kind"])

    def test_uri_validator_rejects_credentials_queries_and_fragments(self) -> None:
        self.assertEqual(URI, canonical_play_uri(URI))
        for value in (
            "https://user@play.modiqo.ai/chetan/report@1.0.0",
            "https://play.modiqo.ai/chetan/report@1.0.0?x=1",
            "https://play.modiqo.ai/chetan/report@1.0.0#x",
            "http://play.modiqo.ai/chetan/report@1.0.0",
            "https://play.modiqo.ai:not-a-port/chetan/report@1.0.0",
        ):
            self.assertIsNone(canonical_play_uri(value))


class RoteGreetingProbeTest(unittest.TestCase):
    @patch("play.onboarding.shutil.which", return_value="/opt/bin/rote")
    def test_probe_reports_live_binary_without_calling_it(self, _which) -> None:
        result = probe_rote()
        self.assertEqual("installed", result["rote_status"])
        self.assertEqual("/opt/bin/rote", result["rote_command"])
        self.assertGreaterEqual(result["probe_ns"], 0)

    @patch("play.onboarding.os.access", return_value=True)
    @patch("play.onboarding.Path.is_file", return_value=True)
    @patch("play.onboarding.shutil.which", return_value=None)
    def test_probe_checks_supported_off_path_locations(self, _which, _is_file, _access) -> None:
        result = probe_rote()
        self.assertEqual("installed", result["rote_status"])
        self.assertTrue(result["rote_off_path"])

    @patch("play.onboarding.subprocess.run")
    @patch("play.onboarding.os.access", return_value=True)
    @patch("play.onboarding.Path.is_file", return_value=True)
    def test_whoami_extracts_email_handle_without_retaining_raw_output(
        self, _is_file, _access, run
    ) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "@@status\nok: Chetan@Modiqo.ai\n"
        run.return_value.stderr = "warning: stale handle lookup\n"
        result = inspect_identity({"onboarding": {"rote_command": "/opt/bin/rote"}})
        self.assertEqual("authenticated", result["identity_status"])
        self.assertEqual("chetan@modiqo.ai", result["email"])
        self.assertEqual("chetan", result["email_handle"])
        self.assertNotIn("warning", str(result))
        self.assertTrue(str(result["identity_ref"]).startswith("sha256:"))

    @patch("play.onboarding.subprocess.run")
    @patch("play.onboarding.os.access", return_value=True)
    @patch("play.onboarding.Path.is_file", return_value=True)
    def test_missing_identity_routes_to_setup_without_fabricating_handle(
        self, _is_file, _access, run
    ) -> None:
        run.return_value.returncode = 1
        run.return_value.stdout = "not logged in"
        run.return_value.stderr = ""
        result = inspect_identity({"onboarding": {"rote_command": "/opt/bin/rote"}})
        self.assertEqual("setup_required", result["identity_status"])
        self.assertIsNone(result["email"])
        self.assertIsNone(result["email_handle"])


class PublicCardTest(unittest.TestCase):
    def test_normalizes_and_formats_install_and_inspect_card(self) -> None:
        card = normalize_card(URI, public_card(), 123)
        self.assertEqual("GITHUB_API_TOKEN", card["adapters"][0]["credential_names"][0])
        self.assertEqual(64, len(card["card_sha256"]))
        markdown = render_card(card)
        self.assertIn(f"`rote play inspect {URI}`", markdown)
        self.assertIn("Guided bootstrap and run", markdown)
        self.assertIn("Install only the Rote CLI", markdown)
        self.assertIn("explicit consent", markdown)

    def test_card_identity_or_effect_mismatch_fails_closed(self) -> None:
        card = public_card()
        card["id"] = "https://play.modiqo.ai/other/report@1.0.0"
        with self.assertRaisesRegex(OnboardingError, "does not match"):
            normalize_card(URI, card, 1)

        card = public_card()
        card["actions"]["inspect"]["effect"] = "write"
        with self.assertRaisesRegex(OnboardingError, "not declared read-only"):
            normalize_card(URI, card, 1)

        card = public_card()
        card["actions"]["bootstrapAndRun"]["requiresConsent"] = False
        with self.assertRaisesRegex(OnboardingError, "must require explicit consent"):
            normalize_card(URI, card, 1)


if __name__ == "__main__":
    unittest.main()
