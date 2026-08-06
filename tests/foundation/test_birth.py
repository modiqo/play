from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from play.birth import (
    BirthError,
    bind_birth,
    birth_listing,
    capture_birth,
    resolve_birth,
    verify_birth,
)
from play.commands import CommandError


class BirthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "play-home"
        self.workspace = self.root / "workspace"
        self.flow_root = self.root / "flow"
        self.workspace.mkdir()
        self.flow_root.mkdir()
        (self.flow_root / "main.ts").write_text("export const answer = 42;\n")
        (self.flow_root / "deps.toml").write_text("[dependencies]\n")
        (self.flow_root / ".rote-flow-lint.json").write_text('{"private":"not evidence"}\n')

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def flow_info(self) -> dict:
        return {
            "name": "weekly-customer-report",
            "description": "Builds the weekly customer report.",
            "format": "typescript",
            "scheme": "v1",
            "version": "0.62.1",
            "status": "released",
            "kind": "atomic",
            "flow_type": "sequential",
            "execution_model": "steps_with_presentation",
            "requires_endpoints": ["adapter/posthog"],
            "requires_sessions": True,
            "package": {
                "root": str(self.flow_root),
                "entry": "main.ts",
                "members": [
                    {"path": "main.ts", "class": "entrypoint", "bytes": 26},
                    {"path": "deps.toml", "class": "identity", "bytes": 15},
                    {"path": ".rote-flow-lint.json", "class": "local", "bytes": 27},
                ],
            },
        }

    def stats(self) -> dict:
        return {
            "name": "weekly-report-build",
            "location": str(self.workspace),
            "commands": 2,
            "responses": 2,
            "variables": 1,
            "execution_mode": "exploration",
            "token_savings": {"tokens_saved": 1200, "basis": "excluded string"},
        }

    def command_log(self) -> list[dict]:
        return [
            {
                "sequence": 1,
                "command_type": "QueryRead",
                "params": '{"api_key":"must-never-be-stored"}',
                "response_ids": "[11]",
                "timestamp": "2026-08-05T01:00:00+00:00",
            },
            {
                "sequence": 2,
                "command_type": "ProcessExec",
                "params": '{"command":"curl private.example"}',
                "response_ids": "[12]",
                "timestamp": "2026-08-05T01:01:30+00:00",
            },
        ]

    def dependencies(self) -> list[dict]:
        return [
            {
                "command_sequence": 2,
                "dependency_type": "response",
                "source_response": 11,
                "source_query": "customer_email=secret@example.com",
                "target_field_path": "params.authorization",
                "variable_name": "private_token",
            }
        ]

    def capture_side_effect(self, *arguments: str, **kwargs):
        if arguments[:2] == ("flow", "info"):
            return self.flow_info()
        if arguments[:2] == ("workspace", "stats"):
            return self.stats()
        if arguments[:2] == ("trace", "--deps"):
            raise CommandError("rote trace --deps --json failed: unexpected argument '--json'")
        if arguments[:3] == ("workspace", "inspect", "log"):
            return self.command_log()
        if arguments[:3] == ("workspace", "inspect", "deps"):
            return self.dependencies()
        raise AssertionError(arguments)

    @patch("play.birth.run_rote_json")
    def test_capture_is_private_redacted_and_idempotent(self, run_rote_json) -> None:
        run_rote_json.side_effect = self.capture_side_effect
        first = capture_birth("weekly-report-build", "weekly-customer-report", home=self.home)
        second = capture_birth("weekly-report-build", "weekly-customer-report", home=self.home)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["sha256"], second["sha256"])
        record_path = Path(first["object_ref"])
        serialized = record_path.read_text()
        for secret in (
            "must-never-be-stored",
            "private.example",
            "secret@example.com",
            "params.authorization",
            "private_token",
            str(self.workspace),
            "not evidence",
        ):
            self.assertNotIn(secret, serialized)
        record = json.loads(serialized)
        self.assertEqual(["adapter", "shell"], record["journey"]["modalities"])
        self.assertEqual(90.0, record["journey"]["duration_seconds"])
        self.assertEqual("workspace-inspect-json-fallback", record["sources"]["trace"])
        self.assertEqual(0o600, stat.S_IMODE(record_path.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(record_path.parent.stat().st_mode))
        self.assertEqual(6, run_rote_json.call_count)

    @patch("play.birth.run_rote_json")
    def test_future_trace_json_is_preferred(self, run_rote_json) -> None:
        def side_effect(*arguments: str, **kwargs):
            if arguments[:2] == ("flow", "info"):
                return self.flow_info()
            if arguments[:2] == ("workspace", "stats"):
                return self.stats()
            if arguments[:2] == ("trace", "--deps"):
                return {"commands": self.command_log(), "dependencies": self.dependencies()}
            raise AssertionError(arguments)

        run_rote_json.side_effect = side_effect
        result = capture_birth("weekly-report-build", "weekly-customer-report", home=self.home)
        _, record, _ = resolve_birth(result["sha256"], home=self.home)
        self.assertEqual("rote-trace-deps-json", record["sources"]["trace"])
        self.assertEqual(3, run_rote_json.call_count)

    @patch("play.birth.run_rote_json")
    def test_non_capability_trace_error_does_not_silently_fallback(self, run_rote_json) -> None:
        def side_effect(*arguments: str, **kwargs):
            if arguments[:2] == ("flow", "info"):
                return self.flow_info()
            if arguments[:2] == ("workspace", "stats"):
                return self.stats()
            raise CommandError("rote trace --deps --json failed: workspace is corrupt")

        run_rote_json.side_effect = side_effect
        with self.assertRaisesRegex(BirthError, "workspace is corrupt"):
            capture_birth("weekly-report-build", "weekly-customer-report", home=self.home)
        self.assertEqual(3, run_rote_json.call_count)

    @patch("play.birth.run_rote_json")
    def test_bind_lookup_list_and_verify(self, run_rote_json) -> None:
        run_rote_json.side_effect = self.capture_side_effect
        captured = capture_birth("weekly-report-build", "weekly-customer-report", home=self.home)
        run_rote_json.side_effect = None
        run_rote_json.return_value = {
            "version": {
                "version": "1.2.3",
                "content_hash": "registry-content-sha",
                "metadata": {"provenance": {"author": "Ada Example <ada@example.com>"}},
            }
        }

        bound = bind_birth(
            captured["sha256"][:12], "modiqo/weekly-customer-report", home=self.home
        )
        self.assertEqual("modiqo/weekly-customer-report@1.2.3", bound["exact_reference"])
        self.assertEqual("Ada Example <ada@example.com>", bound["author"])
        resolved_sha, _, _ = resolve_birth(
            "modiqo/weekly-customer-report@1.2.3", home=self.home
        )
        self.assertEqual(captured["sha256"], resolved_sha)
        self.assertEqual(1, birth_listing(home=self.home)["count"])
        verification = verify_birth("weekly-customer-report", home=self.home)
        self.assertTrue(verification["valid"])
        self.assertTrue(all(verification["checks"].values()))
        listing = birth_listing(home=self.home)["births"][0]
        self.assertEqual(
            "Ada Example <ada@example.com>",
            listing["bindings"]["modiqo/weekly-customer-report@1.2.3"]["author"],
        )

    @patch("play.birth.run_rote_json")
    def test_binding_rejects_a_requested_version_that_is_not_current(self, run_rote_json) -> None:
        run_rote_json.side_effect = self.capture_side_effect
        captured = capture_birth("weekly-report-build", "weekly-customer-report", home=self.home)
        run_rote_json.side_effect = None
        run_rote_json.return_value = {
            "version": {"version": "2.0.0", "content_hash": "registry-content-sha"}
        }
        with self.assertRaisesRegex(BirthError, "registry reports"):
            bind_birth(
                captured["sha256"],
                "modiqo/weekly-customer-report@1.0.0",
                home=self.home,
            )


if __name__ == "__main__":
    unittest.main()
