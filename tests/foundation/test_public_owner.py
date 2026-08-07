from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.public_owner import resolve_public_owners


class PublicOwnerResolutionTest(unittest.TestCase):
    @staticmethod
    def runner(
        *,
        whoami: str,
        orgs: str,
        whoami_code: int = 0,
        org_code: int = 0,
    ):
        def run(command, **_kwargs):
            if command[1:3] == ["registry", "whoami"]:
                return subprocess.CompletedProcess(command, whoami_code, whoami, "")
            return subprocess.CompletedProcess(command, org_code, orgs, "")

        return run

    def test_claimed_handle_and_orgs_are_distinct_typed_choices(self) -> None:
        result = resolve_public_owners(
            rote_command="/usr/local/bin/rote",
            runner=self.runner(
                whoami="@@result\nemail: chetan@modiqo.ai\nhandle: chetan\n",
                orgs=(
                    '[{"slug":"chetanconikee","display_name":"Chetan"},'
                    '{"slug":"modiqo","display_name":"Modiqo Inc"}]'
                ),
            ),
        )["publication"]
        self.assertEqual("choice_required", result["owner_resolution"])
        self.assertEqual("chetan", result["profile_handle"])
        self.assertIsNone(result["owner"])
        self.assertEqual(
            ["chetan", "chetanconikee", "modiqo"],
            [choice["owner"] for choice in result["owner_choices"]],
        )
        self.assertIn("already claimed", result["owner_summary"])
        self.assertIn("`chetanconikee`", result["owner_summary"])

    def test_one_authorized_org_resolves_without_handle_claim(self) -> None:
        result = resolve_public_owners(
            rote_command="/usr/local/bin/rote",
            runner=self.runner(
                whoami="@@result\nemail: chetan@modiqo.ai\n",
                orgs='[{"slug":"chetanconikee","display_name":"Chetan"}]',
            ),
        )["publication"]
        self.assertEqual("resolved", result["owner_resolution"])
        self.assertEqual("chetanconikee", result["owner"])
        self.assertIn("without attempting to claim a handle", result["owner_summary"])

    def test_probe_failure_keeps_private_and_skip_available(self) -> None:
        result = resolve_public_owners(
            rote_command="/usr/local/bin/rote",
            runner=self.runner(whoami="", orgs="[]", whoami_code=1),
        )["publication"]
        self.assertEqual("unavailable", result["owner_resolution"])
        self.assertEqual([], result["owner_choices"])
        self.assertIn("Private save and Skip remain available", result["owner_summary"])


if __name__ == "__main__":
    unittest.main()
