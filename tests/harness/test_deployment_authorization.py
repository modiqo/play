from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GUARD = Path(__file__).resolve().parents[2] / ".github/scripts/require-production-admin.sh"


class DeploymentAuthorizationTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        gh = self.root / "gh"
        gh.write_text(f"#!{sys.executable}\n" + """
import os
import sys
from pathlib import Path

assert sys.argv[1] == 'api'
assert sys.argv[3:] == ['--jq', '.permission']
username = sys.argv[2].split('/')[-2]
assert sys.argv[2] == f'repos/modiqo/play/collaborators/{username}/permission'
with Path(os.environ['TEST_CALLS']).open('a') as calls:
    calls.write(username + '\\n')
permission = os.environ[f'TEST_PERMISSION_{username}']
if permission == 'api-error':
    sys.exit(1)
print(permission)
""")
        gh.chmod(0o755)
        self.env = {
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "modiqo/play",
            "GITHUB_ACTOR": "original",
            "GITHUB_TRIGGERING_ACTOR": "rerunner",
            "TEST_PERMISSION_original": "admin",
            "TEST_PERMISSION_rerunner": "admin",
            "TEST_CALLS": str(self.root / "calls"),
        }

    def authorize(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(GUARD)], env=self.env, capture_output=True, text=True)

    def test_admin_dispatch_and_admin_rerun_are_allowed(self) -> None:
        result = self.authorize()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("original\nrerunner\n", (self.root / "calls").read_text())

    def test_non_admin_original_actor_or_rerunner_is_denied(self) -> None:
        for username in ("original", "rerunner"):
            for permission in ("write", "maintain", "read", "none", "", "null", "api-error"):
                with self.subTest(username=username, permission=permission):
                    self.env[f"TEST_PERMISSION_{username}"] = permission
                    self.assertNotEqual(0, self.authorize().returncode)
            self.env[f"TEST_PERMISSION_{username}"] = "admin"

    def test_only_manual_dispatch_from_main_is_allowed(self) -> None:
        for event, ref in (
            ("push", "refs/heads/main"),
            ("pull_request", "refs/heads/main"),
            ("workflow_dispatch", "refs/heads/feature"),
            ("workflow_dispatch", "refs/tags/v0.4.99"),
        ):
            with self.subTest(event=event, ref=ref):
                self.env.update(GITHUB_EVENT_NAME=event, GITHUB_REF=ref)
                self.assertNotEqual(0, self.authorize().returncode)
        self.assertFalse((self.root / "calls").exists())

    def test_missing_actor_fails_closed(self) -> None:
        for key in ("GITHUB_ACTOR", "GITHUB_TRIGGERING_ACTOR"):
            with self.subTest(key=key):
                original = self.env.pop(key)
                self.assertNotEqual(0, self.authorize().returncode)
                self.env[key] = original


if __name__ == "__main__":
    unittest.main()
