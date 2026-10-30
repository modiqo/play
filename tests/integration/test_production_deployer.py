from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/authorize-production-deployer.sh"
FAKE_GH = """#!/bin/sh
# Serve `gh api repos/<repo>/collaborators/<login>/permission` from $PERMISSIONS.
echo "$2" >> "$GH_CALLS"
login=${2%/permission}
login=${login##*/}
permission=$(awk -v login="$login" '$1 == login { print $2 }' "$PERMISSIONS")
[ -n "$permission" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
echo "$permission"
"""


class ProductionDeployerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.calls = self.root / "gh-calls"
        self.calls.touch()
        self.permissions = self.root / "permissions"
        self.permissions.write_text("owner admin\nmember write\n", encoding="utf-8")
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_CALLS": str(self.calls),
            "PERMISSIONS": str(self.permissions),
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/tags/v1.2.3",
            "GITHUB_REPOSITORY": "modiqo/play",
        }

    def authorize(
        self, actor: str, *, rerunner: str | None = None, deployers: str | None = None, **env: str,
    ) -> subprocess.CompletedProcess[str]:
        variables = {
            **self.env,
            "GITHUB_ACTOR": actor,
            "GITHUB_TRIGGERING_ACTOR": rerunner or actor,
            **env,
        }
        if deployers is not None:
            variables["PRODUCTION_DEPLOYERS"] = deployers
        return subprocess.run(
            ("bash", str(SCRIPT)), env=variables, capture_output=True, text=True, check=False,
        )

    def test_admin_deploys_without_named_deployers(self) -> None:
        self.assertEqual(self.authorize("owner").returncode, 0)

    def test_non_admin_is_rejected_without_a_named_entry(self) -> None:
        for deployers in (None, "", "other"):
            with self.subTest(deployers=deployers):
                result = self.authorize("member", deployers=deployers)
                self.assertEqual(result.returncode, 1)
                self.assertIn("PRODUCTION_DEPLOYERS entry for member", result.stdout)

    def test_named_deployer_is_authorized_without_permission_lookup(self) -> None:
        for deployers in ("member", "other, Member", "other,member", "other\nmember\n", "\tmember "):
            with self.subTest(deployers=deployers):
                self.calls.write_text("", encoding="utf-8")
                self.assertEqual(self.authorize("member", deployers=deployers).returncode, 0)
                self.assertEqual(self.calls.read_text(encoding="utf-8"), "")

    def test_named_entry_must_match_the_whole_login(self) -> None:
        for deployers in ("member-two", "mem", "member*", ".*"):
            with self.subTest(deployers=deployers):
                self.assertEqual(self.authorize("member", deployers=deployers).returncode, 1)

    def test_rerunner_needs_authorization_too(self) -> None:
        self.assertEqual(self.authorize("owner", rerunner="member").returncode, 1)
        self.assertEqual(self.authorize("owner", rerunner="member", deployers="member").returncode, 0)
        self.assertEqual(self.authorize("member", rerunner="owner", deployers="member").returncode, 0)

    def test_permission_lookup_failure_fails_closed(self) -> None:
        self.assertNotEqual(self.authorize("stranger").returncode, 0)

    def test_named_deployer_still_needs_a_dispatched_release_tag(self) -> None:
        for env in (
            {"GITHUB_EVENT_NAME": "push"},
            {"GITHUB_REF": "refs/heads/main"},
            {"GITHUB_REF": "refs/tags/v1.2.3-rc1"},
        ):
            with self.subTest(**env):
                result = self.authorize("member", deployers="member", **env)
                self.assertEqual(result.returncode, 1)
                self.assertIn("vX.Y.Z release tag", result.stdout)


if __name__ == "__main__":
    unittest.main()
