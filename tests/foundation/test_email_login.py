from __future__ import annotations

import http.client
import json
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from scripts.lib.play.email_login import EmailLogin, make_server
from scripts.lib.play.identity import login_command


class EmailLoginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.login = EmailLogin("/bin/rote")
        self.email = "person@example.com"

    @patch("scripts.lib.play.email_login.run_rote")
    def test_released_otp_sends_then_verifies_with_code_only_on_stdin(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "private receipt", "")
        self.assertEqual(200, self.login.submit({"action": "send", "email": self.email})[0])
        send = run.call_args
        self.assertEqual(
            ["/bin/rote", "login", "--otp", "--otp-email", self.email, "--json"], send.args[0]
        )
        self.assertEqual("", send.kwargs["input"])
        status, message = self.login.submit({"action": "verify", "email": self.email, "code": "123456"})
        self.assertEqual(200, status)
        self.assertTrue(self.login.complete)
        self.assertEqual(send.args[0] + ["--otp-verify"], run.call_args.args[0])
        self.assertEqual("123456\n", run.call_args.kwargs["input"])
        self.assertNotIn("123456", str(run.call_args.args))
        self.assertNotIn("private receipt", message)
        self.assertEqual(410, self.login.submit({"action": "send", "email": self.email})[0])

    @patch("scripts.lib.play.email_login.run_rote")
    def test_retry_limits_and_address_binding(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.login.submit({"action": "send", "email": self.email})
        self.assertEqual(429, self.login.submit({"action": "send", "email": self.email})[0])
        self.assertEqual(400, self.login.submit({"action": "verify", "email": "other@example.com", "code": "123456"})[0])
        self.assertEqual(1, run.call_count)
        run.return_value = subprocess.CompletedProcess([], 1, "otp_invalid_or_expired SECRET", "")
        for _ in range(5):
            status, message = self.login.submit({"action": "verify", "email": self.email, "code": "123456"})
            self.assertEqual(400, status)
            self.assertNotIn("SECRET", message)
        self.assertEqual(429, self.login.submit({"action": "verify", "email": self.email, "code": "123456"})[0])
        self.assertFalse(self.login.complete)
        self.assertEqual(6, run.call_count)

    @patch("scripts.lib.play.email_login.run_rote")
    def test_invalid_input_expiry_and_transport_failure_do_not_authenticate(self, run) -> None:
        for body in ({}, {"action": "send", "email": "bad"}, {"action": "unknown", "email": self.email}):
            self.assertEqual(400, self.login.submit(body)[0])
        run.assert_not_called()
        run.side_effect = subprocess.TimeoutExpired([], 45)
        self.assertEqual(503, self.login.submit({"action": "send", "email": self.email})[0])
        self.assertEqual("", self.login.email)
        self.login.deadline = time.monotonic() - 1
        self.assertEqual(410, self.login.submit({"action": "send", "email": self.email})[0])
        self.assertFalse(self.login.complete)

    @patch("scripts.lib.play.email_login.run_rote")
    def test_loopback_form_requires_private_path_host_origin_and_json(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "SECRET", "")
        with make_server(self.login) as server:
            def request(method="POST", path=None, headers=None, body=None):
                thread = threading.Thread(target=server.handle_request)
                thread.start()
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    connection.request(method, path or self.login.path, body=body, headers=headers or {})
                    response = connection.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    connection.close()
                    thread.join(5)

            status, headers, html = request("GET")
            self.assertEqual(200, status)
            self.assertEqual("no-store", headers["Cache-Control"])
            self.assertIn(b"Email me a code", html)
            self.assertEqual(404, request("GET", path="/wrong")[0])
            self.assertEqual(404, request("GET", headers={"Host": "attacker.example"})[0])
            self.assertEqual(403, request(headers={"Origin": "https://attacker.example"})[0])
            self.assertEqual(415, request(headers={"Origin": self.login.origin})[0])
            headers = {"Origin": self.login.origin, "Content-Type": "application/json"}
            self.assertEqual(413, request(headers=headers, body="x" * 2049)[0])
            self.assertEqual(400, request(headers=headers, body="[]")[0])
            run.assert_not_called()
            status, _, body = request(headers=headers, body=json.dumps({"action": "send", "email": self.email}))
            self.assertEqual(200, status)
            self.assertNotIn(b"SECRET", body)
            self.assertNotIn(self.email.encode(), body)

    def test_every_email_caller_selects_play_form_instead_of_custom_rote_provider(self) -> None:
        command = login_command("/bin/rote", "email")
        self.assertTrue(command[1].endswith("email_login.py"))
        self.assertEqual("/bin/rote", command[-1])
        self.assertNotIn("--provider", command)
        self.assertEqual(["/bin/rote", "login", "--provider", "google"], login_command("/bin/rote", "google"))


if __name__ == "__main__":
    unittest.main()
