from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.controller import ControllerEvent, ControllerRuntime, EventId, StateId
from play.identity import last_login_provider, login_command, remember_login_provider
from play.onboarding import OnboardingError, company_setup, login_rote_identity, remember_first_use_orientation
from play.bootstrap import _identity_gate, _login_method_options


class CompanyOnboardingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = ControllerRuntime(ROOT)

    def session(self, state="onboarding_company_check", *, registry=False, uri=False):
        session = self.runtime.initial_session(run_id="signup", task_key="signup", request_original="$play")
        context = copy.deepcopy(dict(session.context))
        context["state"] = state
        context["onboarding"].update({
            "identity_status": "authenticated", "email": "alice@example.com",
            "email_handle": "alice", "identity_ref": "sha256:identity", "whoami_ns": 1,
            "rote_status": "installed", "rote_command": "/tmp/rote",
            "intent": "play_uri" if uri else "greeting", "company_resume_registry": registry,
            "play_uri": "https://play.modiqo.ai/modiqo/hello@0.2.2" if uri else None,
        })
        context["match"]["reference"] = "modiqo/hello@0.2.2"
        context["request"]["parameters"] = {"limit": 3}
        context["inspection"].update({"exact_reference": "modiqo/hello@0.2.2", "disclosure_sha256": "a" * 64})
        return replace(session, cursor=replace(session.cursor, state=StateId(state)), context=context, preflight_ready=True)

    def advance(self, session, event, payload=None):
        return self.runtime.advance_session(session, ControllerEvent(
            id=EventId(event), guards={}, payload=payload or {},
        )).session

    def choice(self, session, event, team=None):
        payload = {"prompt_version": "1", "selected_at": "2026-09-23T00:00:00Z"}
        if team is not None:
            payload["team"] = team
        return self.advance(session, event, payload)

    def required(self, session):
        return self.advance(session, "company_setup_required", {
            "onboarding": {"company_setup_status": "required"}, "evidence_refs": ["sha256:company"],
        })

    def test_skip_preserves_greeting_uri_and_registry_continuations(self):
        for registry, uri, target in [(False, False, "onboarding_experience"), (False, True, "use_inspect"), (True, False, "use_inspect")]:
            with self.subTest(registry=registry, uri=uri):
                session = self.required(self.session(registry=registry, uri=uri))
                self.assertEqual("onboarding_company_offer", session.cursor.state)
                skipped = self.choice(session, "company_setup_skipped")
                self.assertEqual("onboarding_company_record", skipped.cursor.state)
                resumed = self.advance(skipped, "company_setup_recorded", {
                    "onboarding": {"company_setup_status": "handled"}, "evidence_refs": ["sha256:company"],
                })
                self.assertEqual(target, resumed.cursor.state)
                self.assertEqual("modiqo/hello@0.2.2", resumed.context["match"]["reference"])
                self.assertEqual({"limit": 3}, resumed.context["request"]["parameters"])
                self.assertEqual("not_started", resumed.context["team"]["status"])
                self.assertIsNone(resumed.context["team"]["slug"])

    def test_existing_company_marker_skips_offer(self):
        session = self.advance(self.session(), "company_setup_handled", {
            "onboarding": {"company_setup_status": "handled"}, "evidence_refs": ["sha256:company"],
        })
        self.assertEqual("onboarding_experience", session.cursor.state)

    def create_company(self):
        session = self.choice(self.required(self.session()), "onboarding_team_selected")
        self.assertEqual("onboarding_team_name", session.cursor.state)
        session = self.choice(session, "company_name_described", {"name": "Acme Platform"})
        session = self.choice(session, "team_handle_described", {"slug": "acme-platform"})
        self.assertEqual("onboarding_team_create", session.cursor.state)
        self.assertEqual("Acme Platform", session.context["team"]["name"])
        return session

    def test_company_creation_must_succeed_before_invite_and_roles_are_explicit(self):
        session = self.create_company()
        failed = self.advance(session, "team_space_failed", {
            "team": {"slug": "acme-platform", "status": "failed"}, "reason": "Handle is already owned", "evidence_refs": ["sha256:failed"],
        })
        self.assertEqual("blocked", failed.cursor.state)
        ready = self.advance(session, "team_space_ready", {"team": {
            "slug": "acme-platform", "name": "Acme Platform", "status": "ready",
            "members": [{"email": "alice@example.com", "role": "admin"}], "evidence_refs": ["sha256:members"],
        }})
        offered = self.advance(ready, "team_loop_presented", {
            "team": {"status": "presented", "presentation_ref": "sha256:shown"}, "presentation": {"markdown": "Company ready"},
        })
        self.assertEqual("team_invite_offer", offered.cursor.state)
        for event, role in [("team_invite_selected", "developer"), ("team_admin_invite_selected", "admin")]:
            selected = self.choice(offered, event, {"slug": "acme-platform"})
            self.assertEqual(role, selected.context["team"]["invite_role"])
            question = self.runtime.project_session(selected).as_dict()["instruction"]["question"]
            self.assertIn(role, question)
            self.assertIn("acme-platform", question)
            described = self.choice(selected, "team_invite_described", {
                "slug": "acme-platform", "invite_email": "colleague@example.com", "invite_role": role,
            })
            self.assertEqual("team_invite_execute", described.cursor.state)
            self.assertEqual("rote-org", self.runtime.project_session(described).as_dict()["instruction"]["specialist"])
        finished = self.choice(offered, "team_onboarding_finished", {"slug": "acme-platform"})
        self.assertEqual("onboarding_company_record", finished.cursor.state)

    def test_company_marker_is_private_per_identity_and_survives_orientation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "onboarding.json"
            payload = {"onboarding": {"identity_status": "authenticated", "email": "alice@example.com"}}
            self.assertEqual("company_setup_required", company_setup(payload, state_path=path)["event"])
            payload["onboarding"]["company_setup_status"] = "required"
            company_setup(payload, remember=True, state_path=path)
            payload["onboarding"]["orientation_status"] = "presented"
            remember_first_use_orientation(payload, state_path=path)
            self.assertEqual("company_setup_handled", company_setup(payload, state_path=path)["event"])
            self.assertNotIn("alice@example.com", path.read_text())
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            payload["onboarding"]["email"] = "another@example.com"
            self.assertEqual("company_setup_required", company_setup(payload, state_path=path)["event"])

    def test_company_setup_requires_verified_identity_and_valid_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            with self.assertRaises(OnboardingError):
                company_setup({"onboarding": {"email": "alice@example.com"}}, state_path=path)
            path.write_text('{"schema":"invalid"}')
            with self.assertRaises(OnboardingError):
                company_setup({"onboarding": {"identity_status": "authenticated", "email": "alice@example.com"}}, state_path=path)

    def test_email_login_delegates_verification_to_rote_and_stores_only_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identity.json"
            self.assertTrue(remember_login_provider("email", path=path))
            self.assertEqual("email", last_login_provider(path=path))
            self.assertEqual({"schema", "last_login_provider", "verified_at"}, set(json.loads(path.read_text())))
        with patch("play.onboarding._validated_rote_command", return_value="/tmp/rote"), patch("play.onboarding.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "complete", "")) as run, patch("play.onboarding.inspect_identity", return_value={"identity_status":"authenticated", "identity_ref":"sha256:identity"}), patch("play.onboarding.remember_login_provider") as remember:
            result = login_rote_identity({"onboarding": {"rote_command":"/tmp/rote", "login_provider":"email"}})
            self.assertEqual("rote_login_completed", result["event"])
            self.assertEqual(login_command("/tmp/rote", "email"), run.call_args.args[0])
            remember.assert_called_once_with("email")
            self.assertNotIn("code", str(result))

    def test_installer_offers_email_and_verifies_login_before_proceeding(self):
        self.assertIn("email", [method for method, _ in _login_method_options("headed")])
        calls = []
        results = iter([subprocess.CompletedProcess([], 77, "", "login required"), subprocess.CompletedProcess([], 0, "", ""), subprocess.CompletedProcess([], 0, "ok: alice@example.com", "")])
        def runner(command):
            calls.append(command)
            return next(results)
        with patch("play.bootstrap.remember_login_provider"):
            _, authenticated = _identity_gate("/tmp/rote", login_provider="email", runner=runner)
        self.assertTrue(authenticated)
        self.assertEqual(login_command("/tmp/rote", "email"), calls[1])
        self.assertEqual(["/tmp/rote", "whoami", "--check"], calls[2])


if __name__ == "__main__":
    unittest.main()
