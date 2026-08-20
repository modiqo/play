"""Owner-private localhost server for the live Play Journey map."""

from __future__ import annotations

import json
import hashlib
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from collections.abc import Mapping
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .journey import (
    _capture,
    _snapshot_path,
    journey_directory,
    load_graph,
    load_snapshot,
    schedule_worker,
)
from .journey_scene import JourneySceneError, build_scene
from .journey_story import build_story
from .journey_view_catalog import (
    LIVE_ACTIVITY_WINDOW_SECONDS,
    _canonical_path,
    _catalog_capture,
    _pid_running,
    _reference_slug,
    _refresh_workspace_catalog,
    _rote_workspace_root,
    _rote_workspaces,
    _schedule_workspace_projection,
    _selected_workspace_id,
    _workspace_activity,
    _workspace_capture,
    _workspace_catalog,
    _workspace_index,
    _workspace_intent,
    _workspace_recall_origin,
    _workspace_reference,
)
from .journey_view_evidence import (
    EXCHANGE_SCHEMA,
    INTERACTIONS_SCHEMA,
    MAX_COLLECTION_ITEMS,
    MAX_EXCHANGE_CHARS,
    _bounded_exchange,
    _exchange_projection,
    _interaction_projection,
    _redact_exchange_value,
    _redact_text,
)
from .journey_tutorial import TUTORIAL_REFERENCE, tutorial_exchange, tutorial_payload
from .private_store import atomic_write_json, load_json


VIEWER_SCHEMA = "play.journey-viewer/v1"
ASSET_ROOT = Path(__file__).with_name("journey_viewer")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
MAX_LIFETIME_SECONDS = 8 * 60 * 60
PROJECTION_START_TIMEOUT_SECONDS = 4.0


class JourneyViewError(RuntimeError):
    """The local Journey viewer could not be started safely."""



def _ensure_graph_ready(
    capture_ref: str,
    *,
    root: Path | None = None,
    timeout_seconds: float = PROJECTION_START_TIMEOUT_SECONDS,
) -> None:
    """Start a missed projector and wait briefly for its first generation."""

    if load_graph(capture_ref, root=root) is not None:
        return
    capture = _capture(capture_ref)
    if capture is None:
        raise JourneyViewError("The captured exploration is missing or expired")
    if not schedule_worker(capture):
        raise JourneyViewError(
            "The Journey projector could not be started; check whether "
            "PLAY_JOURNEY_DISABLE is set, then retry"
        )
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while time.monotonic() < deadline:
        if load_graph(capture_ref, root=root) is not None:
            return
        time.sleep(0.05)
    raise JourneyViewError(
        "The Journey projector started but its first graph is not ready yet; retry in a moment"
    )


def _viewer_state_path(capture_ref: str, *, root: Path | None = None) -> Path:
    return journey_directory(capture_ref, root=root) / "viewer.json"


def _viewer_asset_sha256() -> str:
    digest = hashlib.sha256()
    for name in ("index.html", "viewer.css", "viewer.js"):
        digest.update(name.encode())
        digest.update((ASSET_ROOT / name).read_bytes())
    return "sha256:" + digest.hexdigest()


def _viewer_implementation_sha256() -> str:
    """Fingerprint both the browser bundle and its resident Python server."""

    digest = hashlib.sha256()
    digest.update(_viewer_asset_sha256().encode())
    module_root = Path(__file__).parent
    for path in sorted(module_root.glob("journey*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    for path in sorted((module_root / "journey_tutorial").glob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _existing_viewer(capture_ref: str, *, root: Path | None = None) -> dict[str, Any] | None:
    try:
        value = load_json(_viewer_state_path(capture_ref, root=root))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != VIEWER_SCHEMA
        or not _pid_running(value.get("pid"))
        or not isinstance(value.get("url"), str)
        or value.get("asset_sha256") != _viewer_asset_sha256()
        or value.get("implementation_sha256") != _viewer_implementation_sha256()
    ):
        return None
    return dict(value)


def _security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")


def _handler_type(
    capture_ref: str, token: str, *, root: Path | None = None
) -> type[BaseHTTPRequestHandler]:
    cookie_name = f"play_journey_{hashlib.sha256(token.encode()).hexdigest()[:12]}"

    class JourneyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *arguments: object) -> None:
            del format, arguments
            return

        def _authorized(self, query: Mapping[str, list[str]]) -> bool:
            supplied = query.get("token", [""])[0]
            if secrets.compare_digest(supplied, token):
                return True
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except Exception:  # pragma: no cover - defensive parser boundary
                return False
            morsel = cookies.get(cookie_name)
            return morsel is not None and secrets.compare_digest(morsel.value, token)

        def _send_bytes(
            self,
            payload: bytes,
            content_type: str,
            *,
            status: int = 200,
            establish_session: bool = False,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if establish_session:
                self.send_header(
                    "Set-Cookie",
                    f"{cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={MAX_LIFETIME_SECONDS}",
                )
            _security_headers(self)
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload: object, *, status: int = 200, etag: str | None = None) -> None:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            if etag:
                self.send_header("ETag", etag)
            _security_headers(self)
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            asset_name = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
            # The application shell is public and contains no captured data. Keeping it
            # reloadable lets the browser recover the API token from sessionStorage;
            # every workspace, story, scene, and event endpoint remains token-gated.
            if asset_name in {"index.html", "viewer.css", "viewer.js"}:
                path = ASSET_ROOT / asset_name
                try:
                    payload = path.read_bytes()
                except OSError:
                    self._send_json({"error": "viewer_asset_missing"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_bytes(
                    payload,
                    CONTENT_TYPES[path.suffix],
                    establish_session=asset_name == "index.html" and self._authorized(query),
                )
                return
            if not self._authorized(query):
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/workspaces":
                self._send_json(_workspace_index(capture_ref, root=root))
                return
            _workspaces, workspace_lookup = _workspace_catalog(capture_ref, root=root)
            requested_workspace = query.get("workspace", [""])[0]
            selected_capture = workspace_lookup.get(requested_workspace, capture_ref)
            if parsed.path == "/api/tutorial":
                if selected_capture != TUTORIAL_REFERENCE:
                    self._send_json({"error": "tutorial_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(tutorial_payload())
                return
            if parsed.path == "/api/scene":
                graph = load_graph(selected_capture, root=root)
                if graph is None:
                    self._send_json({"error": "journey_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                try:
                    scene = build_scene(graph)
                except JourneySceneError as error:
                    self._send_json({"error": str(error)}, status=HTTPStatus.CONFLICT)
                    return
                etag = f'"{scene["scene_sha256"]}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    _security_headers(self)
                    self.end_headers()
                    return
                self._send_json(scene, etag=etag)
                return
            if parsed.path == "/api/story":
                graph = load_graph(selected_capture, root=root)
                if graph is None:
                    self._send_json({"error": "journey_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                story = build_story(graph)
                etag = f'"{story["story_sha256"]}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    _security_headers(self)
                    self.end_headers()
                    return
                self._send_json(story, etag=etag)
                return
            if parsed.path == "/api/interactions":
                graph = load_graph(selected_capture, root=root)
                if graph is None:
                    self._send_json({"error": "journey_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(_interaction_projection(selected_capture, root=root))
                return
            if parsed.path == "/api/exchange":
                raw_sequence = query.get("sequence", [""])[0]
                try:
                    sequence = int(raw_sequence)
                except ValueError:
                    self._send_json({"error": "interaction_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                exchange = (
                    tutorial_exchange(sequence)
                    if selected_capture == TUTORIAL_REFERENCE
                    else _exchange_projection(selected_capture, sequence, root=root)
                )
                if exchange is None:
                    self._send_json({"error": "interaction_unavailable"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(exchange)
                return
            if parsed.path == "/api/events":
                self._events(selected_capture)
                return
            if asset_name != "index.html":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if not self._authorized(query):
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/refresh":
                self._send_json(_refresh_workspace_catalog(capture_ref, root=root))
                return
            if parsed.path != "/api/project":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            _workspaces, workspace_lookup = _workspace_catalog(capture_ref, root=root)
            requested_workspace = query.get("workspace", [""])[0]
            selected_capture = workspace_lookup.get(requested_workspace)
            if selected_capture is None:
                self._send_json({"error": "workspace_unavailable"}, status=HTTPStatus.NOT_FOUND)
                return
            if load_graph(selected_capture, root=root) is not None:
                self._send_json({"status": "ready", "workspace": requested_workspace})
                return
            selected_item = next(
                (item for item in _workspaces if item.get("id") == requested_workspace),
                None,
            )
            capture = (
                _catalog_capture(selected_item, selected_capture)
                if selected_item is not None
                else None
            )
            if capture is None:
                self._send_json({"error": "workspace_unavailable"}, status=HTTPStatus.NOT_FOUND)
                return
            registered = _capture(selected_capture)
            started = (
                schedule_worker(capture)
                if registered is not None
                else _schedule_workspace_projection(capture, root=root)
            )
            if not started:
                self._send_json(
                    {"error": "projector_unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE
                )
                return
            self._send_json(
                {"status": "projecting", "workspace": requested_workspace},
                status=HTTPStatus.ACCEPTED,
            )

        def _events(self, selected_capture: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            _security_headers(self)
            self.end_headers()
            last_fingerprint: tuple[int, int] | None = None
            while True:
                try:
                    stat = _snapshot_path(selected_capture, root=root).stat()
                    fingerprint = (stat.st_size, stat.st_mtime_ns)
                    if fingerprint != last_fingerprint:
                        snapshot = load_snapshot(selected_capture, root=root)
                        event = {
                            "generation": snapshot.get("generation") if snapshot else None,
                            "material_generation": snapshot.get("material_generation") if snapshot else None,
                        }
                        encoded = json.dumps(event, separators=(",", ":"))
                        self.wfile.write(f"event: journey\ndata: {encoded}\n\n".encode())
                        self.wfile.flush()
                        last_fingerprint = fingerprint
                    else:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    time.sleep(0.75)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

    return JourneyHandler


def make_server(
    capture_ref: str,
    token: str,
    *,
    root: Path | None = None,
    port: int = 0,
) -> ThreadingHTTPServer:
    """Create a loopback-only viewer server; caller owns its lifecycle."""

    server = ThreadingHTTPServer(
        ("127.0.0.1", port),
        _handler_type(capture_ref, token, root=root),
    )
    server.daemon_threads = True
    return server


def serve_viewer(
    capture_ref: str,
    token: str,
    *,
    root: Path | None = None,
    port: int = 0,
    lifetime_seconds: int = MAX_LIFETIME_SECONDS,
) -> int:
    server = make_server(capture_ref, token, root=root, port=port)
    server.timeout = 1.0
    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}/?token={urllib.parse.quote(token)}"
    atomic_write_json(
        _viewer_state_path(capture_ref, root=root),
        {
            "schema": VIEWER_SCHEMA,
            "pid": os.getpid(),
            "port": actual_port,
            "url": url,
            "asset_sha256": _viewer_asset_sha256(),
            "implementation_sha256": _viewer_implementation_sha256(),
            "started_at_epoch": time.time(),
        },
    )
    started = time.monotonic()
    try:
        while time.monotonic() - started < max(1, lifetime_seconds):
            server.handle_request()
    finally:
        server.server_close()
    return 0


def launch_viewer(
    capture_ref: str,
    *,
    root: Path | None = None,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Start or reuse the detached viewer without delaying exploration."""

    _ensure_graph_ready(capture_ref, root=root)
    existing = _existing_viewer(capture_ref, root=root)
    if existing is not None:
        if open_browser:
            webbrowser.open(str(existing["url"]))
        return existing
    token = secrets.token_urlsafe(24)
    executable = Path(sys.argv[0]).resolve()
    environment = os.environ.copy()
    if root is not None:
        environment["PLAY_JOURNEY_ROOT"] = str(root)
    command = [
        sys.executable,
        str(executable),
        "serve",
        "--capture",
        capture_ref,
        "--viewer-token",
        token,
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    deadline = time.monotonic() + 3.0
    state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = _existing_viewer(capture_ref, root=root)
        if state is not None and state.get("pid") == process.pid:
            break
        time.sleep(0.05)
    if state is None or state.get("pid") != process.pid:
        raise JourneyViewError("The local Journey viewer did not become ready")
    if open_browser:
        webbrowser.open(str(state["url"]))
    return state
