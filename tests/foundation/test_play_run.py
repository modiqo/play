from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from scripts.lib.play.play_run import PlayRunError, execute


URI = "https://play.modiqo.ai/modiqo/hello@0.1.0"
LATEST_URI = "https://play.modiqo.ai/modiqo/hello"
EXACT = "modiqo/hello@0.1.0"
LATEST = "modiqo/hello"

AUTH_PROTOCOLS = {
    "static": "paste a static credential",
    "oauth": "adapter OAuth reauthorization",
    "oauth_dcr": "browser OAuth with dynamic registration",
    "google_discovery": "browser Google authorization",
}


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


def auth_markers(protocol: str, *, adapter_calls_started: bool = False) -> str:
    return "\n".join(
        (
            "@@status",
            "error: authentication required",
            "@@authentication",
            "Adapter: crucible",
            "Credential: ADAPTER_CRUCIBLE_TOKEN",
            "State: missing",
            f"Protocol: {AUTH_PROTOCOLS[protocol]}",
            "Repair interaction: browser",
            "Network required: yes",
            "Remediation: retry in an interactive terminal to authorize",
            f"Adapter calls started: {str(adapter_calls_started).lower()}",
            "@@next",
            "- retry interactively",
        )
    )


def auth_prose(protocol: str) -> str:
    return "\n".join(
        (
            "Authentication required",
            "  Adapter: crucible",
            "  Credential: ADAPTER_CRUCIBLE_TOKEN",
            "  State: missing",
            f"  Protocol: {AUTH_PROTOCOLS[protocol]}",
            "  Repair interaction: browser",
            "  Network required: yes",
            "  Remediation: retry in an interactive terminal to authorize",
            "  Adapter calls started: false",
        )
    )


def auth_json(protocol: str) -> str:
    return __import__("json").dumps(
        {
            "schema": 1,
            "ok": False,
            "data": {
                "play_auth_required": {
                    "schema": "play.auth-required/v1",
                    "adapter": "crucible",
                    "auth_type": "bearer",
                    "protocol": protocol,
                    "credential": "ADAPTER_CRUCIBLE_TOKEN",
                    "state": "missing",
                    "remedy": "browser_authorize",
                    "automatic_authorization": True,
                    "required_capability": "browser_loopback",
                    "interactive_required": True,
                    "repair_interaction": "browser",
                    "interaction_mode": "non_interactive",
                    "network_required": True,
                    "remediation": "retry in an interactive terminal to authorize",
                    "adapter_calls_started": False,
                }
            },
        }
    )


class UniversalPlayRunTest(unittest.TestCase):
    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_versioned_uri_executes_latest_unversioned_selector_once(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hello output\n", stderr=""
        )

        result = execute(payload())

        self.assertEqual("play_run_ready", result["event"])
        self.assertEqual(LATEST_URI, result["target"])
        self.assertEqual("hello output\n", result["output"]["primary"])
        self.assertEqual("full", result["output"]["detail"])
        run.assert_called_once()
        arguments = run.call_args.args[0]
        self.assertEqual(
            ["/usr/bin/rote", "play", "run", LATEST_URI, "region=us", "--yes"],
            arguments,
        )
        self.assertEqual("structured", run.call_args.kwargs["env"]["ROTE_OUTPUT_MODE"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_non_uri_selection_uses_latest_registry_reference(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="result", stderr=""
        )

        result = execute(payload("modiqo/hello"))

        self.assertEqual(LATEST, result["target"])
        self.assertEqual(LATEST, run.call_args.args[0][3])

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
    def test_marker_auth_failure_routes_every_protocol_to_adapter_config(
        self, run, _which
    ) -> None:
        for protocol in AUTH_PROTOCOLS:
            with self.subTest(protocol=protocol):
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr=auth_markers(protocol)
                )

                result = execute(payload())

                self.assertEqual("play_auth_repair_required", result["event"])
                repair = result["auth_repair"]
                self.assertEqual("rote_auth_repair_required", repair["source"])
                self.assertEqual("rote-adapter-config", repair["owner"])
                self.assertEqual("crucible", repair["adapter_id"])
                self.assertEqual("ADAPTER_CRUCIBLE_TOKEN", repair["env_var"])
                self.assertEqual(protocol, repair["classified_rung"])
                self.assertIn("missing:", repair["distinguishing_error"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_json_auth_failure_routes_every_protocol_to_adapter_config(
        self, run, _which
    ) -> None:
        for protocol in AUTH_PROTOCOLS:
            with self.subTest(protocol=protocol):
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr=auth_json(protocol)
                )

                result = execute(payload())

                self.assertEqual("play_auth_repair_required", result["event"])
                self.assertEqual(protocol, result["auth_repair"]["classified_rung"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_prose_auth_failure_routes_every_protocol_to_adapter_config(
        self, run, _which
    ) -> None:
        for protocol in AUTH_PROTOCOLS:
            with self.subTest(protocol=protocol):
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr=auth_prose(protocol)
                )

                result = execute(payload())

                self.assertEqual("play_auth_repair_required", result["event"])
                self.assertEqual(protocol, result["auth_repair"]["classified_rung"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_unknown_auth_protocol_fails_closed(self, run, _which) -> None:
        output = auth_markers("oauth_dcr").replace(
            AUTH_PROTOCOLS["oauth_dcr"], "future magic auth"
        )
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=output
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])
        self.assertIn("future magic auth", result["reason"])

    @patch("scripts.lib.play.play_run.shutil.which", return_value="/usr/bin/rote")
    @patch("scripts.lib.play.play_run.subprocess.run")
    def test_auth_after_adapter_calls_does_not_enter_repair_loop(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=auth_markers("oauth_dcr", adapter_calls_started=True),
        )

        result = execute(payload())

        self.assertEqual("action_blocked", result["event"])

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
