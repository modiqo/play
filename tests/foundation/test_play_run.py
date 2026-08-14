from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from scripts.lib.play.play_run import PlayRunError, execute


URI = "https://play.modiqo.ai/modiqo/hello@0.1.0"
EXACT = "modiqo/hello@0.1.0"


def payload(reference: str = URI) -> dict:
    parameters = {"region": "us"}
    return {
        "match": {"reference": reference},
        "inspection": {
            "exact_reference": EXACT,
            "disclosure_sha256": "a" * 64,
            "local_change": "none",
        },
        "request": {"parameters": parameters},
        "output_policy": {
            "mode": "detailed",
            "preferred_presentation": "human",
            "max_inline_bytes": 200_000,
            "overflow": "artifact",
        },
        "auth_repair": {
            "original_packet": {
                "exact_reference": EXACT,
                "disclosure_sha256": "a" * 64,
                "parameters": parameters,
            },
            "original_packet_sha256": "b" * 64,
        },
    }


class UniversalPlayRunTest(unittest.TestCase):
    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_uses_approved_uri_once_and_preserves_output(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hello output\n", stderr=""
        )

        result = execute(payload())

        self.assertEqual("play_run_ready", result["event"])
        self.assertEqual(URI, result["target"])
        self.assertEqual("hello output\n", result["output"]["primary"])
        self.assertEqual("full", result["output"]["detail"])
        run.assert_called_once()
        arguments = run.call_args.args[0]
        self.assertEqual(
            ["/usr/bin/rote", "play", "run", URI, "region=us", "--yes"],
            arguments,
        )

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_non_uri_selection_uses_exact_registry_reference(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="result", stderr=""
        )

        result = execute(payload("modiqo/hello"))

        self.assertEqual(EXACT, result["target"])
        self.assertEqual(EXACT, run.call_args.args[0][3])

    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_packet_mismatch_blocks_before_execution(self, run) -> None:
        request = payload()
        request["auth_repair"]["original_packet"]["disclosure_sha256"] = "c" * 64

        with self.assertRaisesRegex(PlayRunError, "digest differs"):
            execute(request)

        run.assert_not_called()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_generic_failure_blocks_with_rotes_own_words_not_drift(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="one failure"
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertEqual("one failure", result["reason"])
        self.assertTrue(result["recoverable"])
        run.assert_called_once()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_drift_event_is_reserved_for_drift_evidence(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="artifact hash mismatch after pull"
        )

        result = execute(payload())

        self.assertEqual("play_drifted", result["event"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_registry_login_failure_names_its_remedy(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="@@status\nerror: Not logged in\n@@next\n- rote login"
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertIn("rote login", result["reason"])
        self.assertIn("retry this exact Play", result["reason"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_structured_auth_failure_routes_to_adapter_config(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr='{"auth_repair":{"adapter_id":"github","env_var":"GITHUB_TOKEN","classified_rung":"static","distinguishing_error":"expired"}}',
        )

        result = execute(payload())

        self.assertEqual("play_auth_repair_required", result["event"])
        self.assertEqual("rote-adapter-config", result["auth_repair"]["owner"])
        run.assert_called_once()

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_large_output_is_bounded_and_preserved_as_private_artifact(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="é" * 100, stderr=""
        )
        request = payload()
        request["output_policy"]["max_inline_bytes"] = 21

        with __import__("tempfile").TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"PLAY_STATE_HOME": directory}):
                result = execute(request)

        self.assertTrue(result["output"]["truncated"])
        self.assertLessEqual(len(result["output"]["primary"].encode()), 21)
        self.assertTrue(result["output"]["full_output_ref"].startswith("file:"))
        self.assertEqual(
            [result["output"]["full_output_ref"]], result["artifact_refs"]
        )


if __name__ == "__main__":
    unittest.main()
