from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.lib.play.identity import (
    last_login_provider,
    recover_rote_session,
    remember_login_provider,
    rote_session_status,
)


class IdentityPreferenceTest(unittest.TestCase):
    def test_silent_success_is_authenticated(self) -> None:
        result = subprocess.CompletedProcess([], 0, "", "")

        self.assertEqual("authenticated", rote_session_status(result))

    def test_verified_provider_round_trips_without_identity_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identity-preference.json"

            self.assertTrue(remember_login_provider("github", path=path))

            self.assertEqual("github", last_login_provider(path=path))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                {"last_login_provider", "schema", "verified_at"}, set(payload)
            )
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_unknown_or_malformed_preferences_require_an_explicit_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identity-preference.json"

            self.assertFalse(remember_login_provider("sso", path=path))
            self.assertIsNone(last_login_provider(path=path))
            path.write_text('{"last_login_provider":"google"}', encoding="utf-8")
            self.assertIsNone(last_login_provider(path=path))

    def test_expired_session_reuses_provider_and_rechecks_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identity-preference.json"
            self.assertTrue(remember_login_provider("github", path=path))
            checks = []
            check_results = iter(
                (
                    subprocess.CompletedProcess([], 77, "", "authentication required"),
                    subprocess.CompletedProcess([], 0, "ok: person@example.com\n", ""),
                )
            )
            logins = []

            status, provider = recover_rote_session(
                "/bin/rote",
                check_runner=lambda command: checks.append(list(command))
                or next(check_results),
                login_runner=lambda command: logins.append(list(command))
                or subprocess.CompletedProcess(command, 0, "", ""),
                preference_path=path,
            )

            self.assertEqual("recovered", status)
            self.assertEqual("github", provider)
            self.assertEqual(
                [
                    ["/bin/rote", "whoami", "--check"],
                    ["/bin/rote", "whoami", "--check"],
                ],
                checks,
            )
            self.assertEqual(
                [["/bin/rote", "login", "--provider", "github"]], logins
            )

    def test_operational_failure_never_starts_login(self) -> None:
        logins = []

        status, provider = recover_rote_session(
            "/bin/rote",
            check_runner=lambda command: subprocess.CompletedProcess(
                command, 1, "", "network error"
            ),
            login_runner=lambda command: logins.append(list(command))
            or subprocess.CompletedProcess(command, 0, "", ""),
        )

        self.assertEqual("error", status)
        self.assertIsNone(provider)
        self.assertEqual([], logins)


if __name__ == "__main__":
    unittest.main()
