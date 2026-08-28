from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.onboarding import (
    OnboardingError,
    STARTER_PLAY_URI,
    canonical_play_uri,
    check_onboarding_experience,
    classify_invocation,
    inspect_identity,
    normalize_card,
    prepare_exploration_welcome,
    prepare_first_play_activation,
    prepare_first_use_orientation,
    prepare_team_loop,
    probe_rote,
    remember_first_use_orientation,
    render_card,
    render_exploration_welcome,
    render_first_use_orientation,
    render_team_loop,
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
    def test_settle_without_a_prework_capture_handle_is_rejected(self) -> None:
        result = classify_invocation("$play settle finished the work")

        self.assertEqual("settle_rejected", result["invocation_kind"])
        self.assertIn("capture handle", result["reason"])

    @patch("play.onboarding.capture_for_settle")
    def test_settle_binds_only_the_explicit_verified_capture(self, resolve) -> None:
        resolve.return_value = {
            "intent": "deploy staging",
            "task_class": "build-ship-chore",
            "reason": "repeatable deployment",
            "workspace": "play-capture-abcdefghijklmnop",
            "trajectory_ref": "sha256:trajectory",
        }

        result = classify_invocation(
            "$play settle cap_abcdefghijklmnop deployment verified"
        )

        resolve.assert_called_once_with("cap_abcdefghijklmnop")
        self.assertEqual("settled", result["invocation_kind"])
        self.assertEqual("verified", result["capture"]["status"])
        self.assertEqual(
            "play-capture-abcdefghijklmnop", result["execution"]["workspace"]
        )

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

    def test_canonical_uri_binds_explicit_parameters_without_model_work(self) -> None:
        result = classify_invocation(
            f"{URI} start_date=2026-07-01 end_date=2026-07-31 providers=all"
        )
        self.assertEqual("play_uri", result["invocation_kind"])
        self.assertEqual(URI, result["play_uri"])
        self.assertEqual(
            {
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
                "providers": "all",
            },
            result["parameters"],
        )

    def test_unambiguous_outcome_verbs_bypass_model_qualification(self) -> None:
        for value in (
            "retrieve rideshare receipts",
            "$play fetch recent emails",
            "Can you help me find expense reports?",
        ):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("outcome", result["invocation_kind"])
                self.assertTrue(result["intent"])

    def test_run_hello_binds_the_pinned_uri_without_model_qualification(self) -> None:
        for value in (
            "run hello",
            "Run the Hello Play",
            "$play run hello",
        ):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("play_uri", result["invocation_kind"])
                self.assertEqual(STARTER_PLAY_URI, result["play_uri"])

    def test_unqualified_named_run_enters_qualified_search(self) -> None:
        for value, intent in (
            ("play run hello", "hello"),
            ("$play run weekly-report", "weekly-report"),
            ("/play run the weekly report", "the weekly report"),
        ):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("search", result["invocation_kind"])
                self.assertEqual(intent, result["intent"])
                self.assertIsNone(result["play_uri"])

    def test_qualified_named_run_remains_available_for_exact_resolution(self) -> None:
        result = classify_invocation("play run alpha/weekly-report")
        self.assertEqual("ordinary", result["invocation_kind"])

    def test_activation_without_a_task_enters_onboarding(self) -> None:
        for value in (
            'User activated the skill "play". Follow the loaded skill instructions.',
            'The user has activated the "play" skill.',
        ):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("greeting", result["invocation_kind"])
                self.assertIsNone(result["play_uri"])

    def test_noncanonical_hosts_and_nonempty_requests_remain_ordinary(self) -> None:
        for value in (
            "/play create a report",
            "https://example.com/chetan/report@1.0.0",
            "file:///etc/passwd",
        ):
            with self.subTest(value=value):
                self.assertEqual("ordinary", classify_invocation(value)["invocation_kind"])

    def test_awareness_aliases_bypass_model_qualification(self) -> None:
        for value in ("$play what's new", "/play whats new", "popular Plays", "trending"):
            with self.subTest(value=value):
                result = classify_invocation(value)
                self.assertEqual("awareness", result["invocation_kind"])
                self.assertEqual(7, result["window_days"])

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

    @patch("play.onboarding.subprocess.Popen")
    @patch("play.onboarding.subprocess.run")
    @patch("play.onboarding.os.access", return_value=True)
    @patch("play.onboarding.Path.is_file", return_value=True)
    def test_whoami_extracts_email_handle_without_retaining_raw_output(
        self, _is_file, _access, run, popen
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
        popen.assert_called_once()
        self.assertIn("refresh", popen.call_args.args[0])

    @patch("play.onboarding.subprocess.Popen")
    @patch("play.onboarding.subprocess.run")
    @patch("play.onboarding.os.access", return_value=True)
    @patch("play.onboarding.Path.is_file", return_value=True)
    def test_missing_identity_routes_to_setup_without_fabricating_handle(
        self, _is_file, _access, run, popen
    ) -> None:
        run.return_value.returncode = 1
        run.return_value.stdout = "not logged in"
        run.return_value.stderr = ""
        result = inspect_identity({"onboarding": {"rote_command": "/opt/bin/rote"}})
        self.assertEqual("setup_required", result["identity_status"])
        self.assertIsNone(result["email"])
        self.assertIsNone(result["email_handle"])
        popen.assert_not_called()


class ExplorationWelcomeTest(unittest.TestCase):
    def test_reuses_authenticated_onboarding_handle_without_another_probe(self) -> None:
        with patch("play.onboarding.probe_rote") as probe:
            result = prepare_exploration_welcome(
                {
                    "onboarding": {
                        "identity_status": "authenticated",
                        "email_handle": "chetan",
                        "identity_ref": "sha256:identity",
                    }
                }
            )

        probe.assert_not_called()
        exploration = result["exploration"]
        self.assertEqual("chetan", exploration["human_name"])
        self.assertEqual("onboarding_email_handle", exploration["identity_source"])
        self.assertIn("You are the expert in this work", result["presentation_markdown"])
        self.assertIn("I am your apprentice", result["presentation_markdown"])
        self.assertIn("your team, or the community", result["presentation_markdown"])

    @patch("play.onboarding.inspect_identity")
    @patch("play.onboarding.probe_rote")
    def test_live_identity_is_used_without_retaining_the_email(self, probe, identity) -> None:
        probe.return_value = {
            "rote_status": "installed",
            "rote_command": "/opt/bin/rote",
        }
        identity.return_value = {
            "identity_status": "authenticated",
            "email": "chetan@modiqo.ai",
            "email_handle": "chetan",
            "identity_ref": "sha256:identity",
        }

        result = prepare_exploration_welcome({"onboarding": {}})

        self.assertEqual("live_email_handle", result["exploration"]["identity_source"])
        self.assertNotIn("chetan@modiqo.ai", str(result))

    @patch("play.onboarding.probe_rote", return_value={"rote_status": "missing"})
    def test_missing_identity_uses_neutral_fallback_without_inventing_a_name(
        self, _probe
    ) -> None:
        result = prepare_exploration_welcome({"onboarding": {}})

        exploration = result["exploration"]
        self.assertIsNone(exploration["human_name"])
        self.assertEqual("unavailable", exploration["identity_status"])
        self.assertEqual("neutral_fallback", exploration["identity_source"])
        self.assertIn("Welcome, friend", result["presentation_markdown"])

    @patch("play.onboarding.inspect_identity", side_effect=OnboardingError("probe timed out"))
    @patch(
        "play.onboarding.probe_rote",
        return_value={"rote_status": "installed", "rote_command": "/opt/bin/rote"},
    )
    def test_identity_probe_failure_still_presents_the_neutral_welcome(
        self, _probe, _identity
    ) -> None:
        result = prepare_exploration_welcome({"onboarding": {}})

        exploration = result["exploration"]
        self.assertEqual("presented", exploration["welcome_status"])
        self.assertEqual("neutral_fallback", exploration["identity_source"])
        self.assertTrue(str(exploration["identity_ref"]).startswith("sha256:"))

    def test_renderer_has_the_human_expert_apprentice_contract(self) -> None:
        rendered = render_exploration_welcome("Ada")
        self.assertIn("Welcome, Ada", rendered)
        self.assertIn("You are the expert in this work", rendered)
        self.assertIn("I am your apprentice", rendered)
        self.assertIn("only when you choose", rendered)


class FirstUseOrientationTest(unittest.TestCase):
    def test_first_use_is_remembered_by_hash_without_storing_email(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "onboarding-state.json"
            payload = {
                "onboarding": {
                    "email": "Ada@Example.com",
                    "email_handle": "ada",
                    "orientation_status": "presented",
                }
            }
            first = check_onboarding_experience(payload, state_path=state_path)
            self.assertEqual("first_use", first["experience_status"])

            recorded = remember_first_use_orientation(payload, state_path=state_path)
            self.assertEqual("recorded", recorded["orientation_status"])
            self.assertEqual(0o600, state_path.stat().st_mode & 0o777)
            self.assertNotIn("ada@example.com", state_path.read_text().lower())

            returning = check_onboarding_experience(payload, state_path=state_path)
            self.assertEqual("returning", returning["experience_status"])
            self.assertEqual(first["experience_ref"], returning["experience_ref"])

    def test_orientation_explains_creation_control_and_return_in_plain_words(self) -> None:
        rendered = render_first_use_orientation("Ada")
        self.assertIn("Start small. See what happens. Stay in control.", rendered)
        self.assertIn("Run Hello", rendered)
        self.assertIn("no account or credentials", rendered)
        self.assertIn("You provide the goals, rules, and exceptions", rendered)
        self.assertIn("Nothing is downloaded or run without", rendered)
        self.assertIn("Create a team space", rendered)
        self.assertIn("learn → teach → learn", rendered)
        self.assertIn("paste-ready X and LinkedIn", rendered)
        self.assertIn("never posts them for you", rendered)

        result = prepare_first_use_orientation(
            {"onboarding": {"email_handle": "Ada Example"}}
        )
        self.assertEqual(STARTER_PLAY_URI, result["starter_reference"])
        self.assertEqual("presented", result["orientation_status"])
        self.assertTrue(str(result["orientation_ref"]).startswith("sha256:"))

    def test_activation_requires_completed_starter_and_keeps_full_result_separate(self) -> None:
        with self.assertRaisesRegex(OnboardingError, "completed starter"):
            prepare_first_play_activation(
                {"onboarding": {"starter_status": "selected", "email_handle": "ada"}}
            )
        result = prepare_first_play_activation(
            {"onboarding": {"starter_status": "completed", "email_handle": "ada"}}
        )
        self.assertIn("Your first Play is complete", result["presentation_markdown"])
        self.assertIn("full result above", result["presentation_markdown"])
        self.assertIn("Inspect — see the X-ray", result["presentation_markdown"])
        self.assertIn("Approve — set the boundary", result["presentation_markdown"])
        self.assertIn("Verify — prove the outcome", result["presentation_markdown"])
        self.assertIn(
            "rote play inspect modiqo/hello --json",
            result["presentation_markdown"],
        )
        self.assertIn("rote play run modiqo/hello", result["presentation_markdown"])
        self.assertIn("cannot be turned into a Play afterward", result["presentation_markdown"])

    def test_team_loop_is_reusable_and_does_not_claim_external_sharing(self) -> None:
        rendered = render_team_loop("Ada Labs", "ada-labs")
        self.assertIn("Team space ready: Ada Labs", rendered)
        self.assertIn("Team handle: `ada-labs`", rendered)
        self.assertIn("review, improve, and use Plays together", rendered)
        self.assertIn("learn in real work → teach", rendered)
        self.assertIn("paste-ready X and LinkedIn", rendered)
        self.assertIn("Nothing has been published", rendered)

        result = prepare_team_loop(
            {
                "team": {
                    "slug": "ada-labs",
                    "name": "Ada Labs",
                    "status": "ready",
                    "members": [],
                }
            }
        )
        self.assertEqual("presented", result["team"]["status"])
        self.assertTrue(str(result["team"]["presentation_ref"]).startswith("sha256:"))


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

    def test_versionless_request_accepts_the_registry_pinned_card(self) -> None:
        versionless = URI.rsplit("@", 1)[0]
        card = normalize_card(versionless, public_card(), 1)
        self.assertEqual(URI, card["uri"])

    def test_versionless_request_still_rejects_a_different_play(self) -> None:
        versionless = URI.rsplit("@", 1)[0]
        card = public_card()
        card["id"] = "https://play.modiqo.ai/other/report@1.0.0"
        with self.assertRaisesRegex(OnboardingError, "does not match"):
            normalize_card(versionless, card, 1)

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
