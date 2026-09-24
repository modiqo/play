"""Play's private browser form for the released Rote email-code interface."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
from subprocess import run as run_rote
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


class EmailLogin:
    def __init__(self, rote: str) -> None:
        self.rote = rote
        self.path = "/" + secrets.token_urlsafe(32)
        self.origin = ""
        self.email = ""
        self.sent_at = 0.0
        self.failures = 0
        self.complete = False
        self.deadline = time.monotonic() + 600

    def submit(self, body: dict[str, Any]) -> tuple[int, str]:
        if self.complete or time.monotonic() >= self.deadline:
            return 410, "This sign-in has ended. Start again from Play."
        action = body.get("action")
        email = body.get("email")
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return 400, "Enter a valid email address."
        command = [self.rote, "login", "--otp", "--otp-email", email, "--json"]
        code = ""
        if action == "send":
            if time.monotonic() - self.sent_at < 60:
                return 429, "Wait one minute before requesting another code."
        elif action == "verify":
            code = body.get("code", "")
            if email != self.email or not self.email:
                return 400, "Request a code for this address first."
            if self.failures >= 5:
                return 429, "Request a new code before trying again."
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
                return 400, "Enter the six-digit code from your email."
            command.append("--otp-verify")
        else:
            return 400, "Unknown sign-in action."
        try:
            # The code travels only through stdin, never process arguments or chat.
            result = run_rote(
                command, input=code + "\n" if code else "", text=True,
                capture_output=True, check=False, timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 503, "Rote could not complete the request. Please try again."
        if result.returncode:
            if action == "verify":
                self.failures += 1
            output = (result.stdout or "") + (result.stderr or "")
            messages = {
                "otp_rate_limited": "Too many requests. Wait before trying again.",
                "otp_invalid_or_expired": "The code is invalid or expired. Try again or request a new code.",
                "otp_policy_denied": "This account cannot sign in under the current organization policy.",
                "otp_unavailable": "Email sign-in is currently unavailable. Choose Google or GitHub in Play.",
                "otp_delivery_failed": "The email could not be delivered. Please try again.",
            }
            for kind, message in messages.items():
                if kind in output:
                    return 400, message
            return 400, "Sign-in did not complete. Check your connection and that Rote supports email codes (0.85.0 or newer)."
        if action == "send":
            self.email, self.sent_at, self.failures = email, time.monotonic(), 0
            return 200, "Check your email for a six-digit code."
        self.complete = True
        return 200, "Signed in. Return to Play to continue."


def make_server(login: EmailLogin) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Do not log email addresses, codes, or the private form URL.

        def reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self) -> bool:
            return self.path == login.path and self.headers.get("Host") == login.origin.removeprefix("http://")

        def do_GET(self) -> None:
            if not self.allowed():
                self.reply(404, b"{}")
                return
            self.reply(200, Path(__file__).with_suffix(".html").read_bytes(), "text/html; charset=utf-8")

        def do_POST(self) -> None:
            if not self.allowed() or self.headers.get("Origin") != login.origin:
                self.reply(403, b"{}")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.reply(415, b"{}")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2048:
                    self.reply(413, b"{}")
                    return
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("expected object")
            except (ValueError, UnicodeError, TimeoutError):
                self.reply(400, b"{}")
                return
            status, message = login.submit(body)
            self.reply(status, json.dumps({"message": message, "complete": login.complete}).encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.5
    login.origin = f"http://127.0.0.1:{server.server_port}"
    return server


def main(rote: str) -> int:
    login = EmailLogin(rote)
    with make_server(login) as server:
        url = login.origin + login.path
        print(f"Complete email sign-in in your browser: {url}", file=sys.stderr, flush=True)
        webbrowser.open(url)
        while not login.complete and time.monotonic() < login.deadline:
            server.handle_request()
    print("Email sign-in complete." if login.complete else "Email sign-in timed out.", file=sys.stderr)
    return 0 if login.complete else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
