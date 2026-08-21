"""Owner-private localhost server for the live Play Journey map."""

from __future__ import annotations

import json
import hashlib
import fcntl
import os
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections.abc import Mapping
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .journey import (
    JourneyError,
    _capture,
    _snapshot_path,
    journey_directory,
    journey_root,
    load_graph,
    load_snapshot,
    refresh_capture,
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
DEFAULT_VIEWER_PORT = 52050
VIEWER_STOP_TIMEOUT_SECONDS = 2.0
VIEWER_KILL_SETTLE_SECONDS = 1.0
VIEWER_PORT_SETTLE_SECONDS = 2.0
VIEWER_START_ATTEMPTS = 2
WORKSPACE_SYNC_INTERVAL_SECONDS = 1.0


class JourneyViewError(RuntimeError):
    """The local Journey viewer could not be started safely."""



def _ensure_graph_ready(
    capture_ref: str,
    *,
    capture: Mapping[str, Any] | None = None,
    root: Path | None = None,
    timeout_seconds: float = PROJECTION_START_TIMEOUT_SECONDS,
) -> None:
    """Start a missed projector and wait briefly for its first generation."""

    if capture is not None:
        try:
            refresh_capture(capture, root=root)
        except JourneyError as error:
            raise JourneyViewError(f"The Rote workspace could not be synchronized: {error}") from error
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
    """Return the single owner-private viewer state, independent of capture."""

    del capture_ref
    return journey_root(root) / "viewer.json"


def _viewer_state_paths(*, root: Path | None = None) -> list[Path]:
    """Include the singleton state and legacy per-capture states for cleanup."""

    base = journey_root(root)
    return [base / "viewer.json", *sorted(base.glob("journey-*/viewer.json"))]


def _journey_server_pids_from_process_list(processes: str) -> set[int]:
    """Select only detached Play Journey HTTP servers from a process listing."""

    selected: set[int] = set()
    for line in processes.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        try:
            command = shlex.split(fields[1])
        except ValueError:
            continue
        launcher_indexes = [
            index for index, value in enumerate(command) if Path(value).name == "play-journey"
        ]
        if any(
            index + 1 < len(command)
            and command[index + 1] == "serve"
            and "--viewer-token" in command[index + 2 :]
            for index in launcher_indexes
        ):
            selected.add(int(fields[0]))
    return selected


def _journey_server_pids(*, root: Path | None = None) -> set[int]:
    selected: set[int] = set()
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        selected.update(_journey_server_pids_from_process_list(result.stdout))
    except (OSError, subprocess.SubprocessError):
        pass
    for path in _viewer_state_paths(root=root):
        try:
            state = load_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(state, Mapping) or state.get("schema") != VIEWER_SCHEMA:
            continue
        pid = state.get("pid")
        port = state.get("port")
        if (
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > 0
            and isinstance(port, int)
            and not isinstance(port, bool)
            and 0 < port <= 65535
            and _pid_running(pid)
            and (pid in selected or _viewer_state_serves_expected_assets(state))
        ):
            selected.add(pid)
    selected.discard(os.getpid())
    return selected


def _viewer_state_serves_expected_assets(state: Mapping[str, Any]) -> bool:
    """Confirm a state PID's recorded port still serves its Journey asset bundle."""

    port = state.get("port")
    expected = state.get("asset_sha256")
    if (
        not isinstance(port, int)
        or isinstance(port, bool)
        or not 0 < port <= 65535
        or not isinstance(expected, str)
    ):
        return False
    digest = hashlib.sha256()
    connection = HTTPConnection("127.0.0.1", port, timeout=0.5)
    try:
        for name in ("index.html", "viewer.css", "viewer.js"):
            connection.request("GET", f"/{name}")
            response = connection.getresponse()
            if response.status != HTTPStatus.OK:
                return False
            digest.update(name.encode())
            digest.update(response.read())
    except (HTTPException, OSError, TimeoutError):
        return False
    finally:
        connection.close()
    return secrets.compare_digest(expected, "sha256:" + digest.hexdigest())


def _stop_journey_viewers(*, root: Path | None = None) -> list[int]:
    """Stop every detached Journey HTTP server and clear its transient state."""

    pids = sorted(_journey_server_pids(root=root))
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            raise JourneyViewError(f"Cannot stop existing Journey viewer process {pid}") from error
    deadline = time.monotonic() + VIEWER_STOP_TIMEOUT_SECONDS
    while any(_pid_running(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    for pid in pids:
        if not _pid_running(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    settle_deadline = time.monotonic() + VIEWER_KILL_SETTLE_SECONDS
    while any(_pid_running(pid) for pid in pids) and time.monotonic() < settle_deadline:
        time.sleep(0.05)
    for path in _viewer_state_paths(root=root):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            continue
    return pids


def _wait_for_viewer_port(
    port: int, *, timeout_seconds: float = VIEWER_PORT_SETTLE_SECONDS
) -> bool:
    """Wait until the fixed loopback port can be rebound after singleton shutdown."""

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
        finally:
            probe.close()
        time.sleep(0.05)


@contextmanager
def _viewer_launch_lock(*, root: Path | None = None):
    path = journey_root(root) / "viewer.lock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
        or value.get("capture_ref") != capture_ref
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


class JourneyThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _sync_workspace(
    capture: Mapping[str, Any], stop: threading.Event, *, root: Path | None = None
) -> None:
    """Continuously reconcile one attached Rote workspace into the Journey graph."""

    while not stop.is_set():
        try:
            refresh_capture(capture, root=root)
        except JourneyError:
            pass
        stop.wait(WORKSPACE_SYNC_INTERVAL_SECONDS)


def make_server(
    capture_ref: str,
    token: str,
    *,
    root: Path | None = None,
    port: int = 0,
) -> ThreadingHTTPServer:
    """Create a loopback-only viewer server; caller owns its lifecycle."""

    server = JourneyThreadingHTTPServer(
        ("127.0.0.1", port),
        _handler_type(capture_ref, token, root=root),
    )
    return server


def serve_viewer(
    capture_ref: str,
    token: str,
    *,
    root: Path | None = None,
    port: int = DEFAULT_VIEWER_PORT,
    lifetime_seconds: int = MAX_LIFETIME_SECONDS,
    workspace_path: str | None = None,
) -> int:
    server = make_server(capture_ref, token, root=root, port=port)
    sync_stop = threading.Event()
    sync_thread: threading.Thread | None = None
    if workspace_path:
        registered = _capture(capture_ref)
        sync_capture = (
            registered
            if registered is not None
            else {
                **_workspace_capture(Path(workspace_path), status="active"),
                "reference": capture_ref,
            }
        )
        sync_thread = threading.Thread(
            target=_sync_workspace,
            args=(sync_capture, sync_stop),
            kwargs={"root": root},
            name="play-journey-workspace-sync",
            daemon=True,
        )
        sync_thread.start()
    server.timeout = 1.0
    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}/?token={urllib.parse.quote(token)}"
    atomic_write_json(
        _viewer_state_path(capture_ref, root=root),
        {
            "schema": VIEWER_SCHEMA,
            "pid": os.getpid(),
            "capture_ref": capture_ref,
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
        sync_stop.set()
        if sync_thread is not None:
            sync_thread.join(timeout=2.0)
        server.server_close()
        try:
            state = load_json(_viewer_state_path(capture_ref, root=root))
            if isinstance(state, Mapping) and state.get("pid") == os.getpid():
                _viewer_state_path(capture_ref, root=root).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    return 0


def launch_viewer(
    capture_ref: str,
    *,
    capture: Mapping[str, Any] | None = None,
    root: Path | None = None,
    open_browser: bool = True,
    port: int = DEFAULT_VIEWER_PORT,
) -> dict[str, Any]:
    """Replace every detached Journey server with one singleton fixed-port server."""

    _ensure_graph_ready(capture_ref, capture=capture, root=root)
    selected_port = max(1, min(65535, int(port)))
    with _viewer_launch_lock(root=root):
        stopped = _stop_journey_viewers(root=root)
        if not _wait_for_viewer_port(selected_port):
            previous = f" after stopping {len(stopped)} older viewer{'s' if len(stopped) != 1 else ''}" if stopped else ""
            raise JourneyViewError(
                f"The local Journey viewer port 127.0.0.1:{selected_port} remained occupied{previous}; "
                "stop the process holding that port or choose another port with --port"
            )
        executable = Path(sys.argv[0]).resolve()
        environment = os.environ.copy()
        if root is not None:
            environment["PLAY_JOURNEY_ROOT"] = str(root)
        workspace_value = capture.get("workspace_path") if capture is not None else None
        state: dict[str, Any] | None = None
        process: subprocess.Popen[bytes] | None = None
        for attempt in range(VIEWER_START_ATTEMPTS):
            token = secrets.token_urlsafe(24)
            command = [
                sys.executable,
                str(executable),
                "serve",
                "--capture",
                capture_ref,
                "--viewer-token",
                token,
                "--port",
                str(selected_port),
            ]
            if isinstance(workspace_value, str) and workspace_value:
                command.extend(["--workspace-path", workspace_value])
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                state = _existing_viewer(capture_ref, root=root)
                if state is not None and state.get("pid") == process.pid:
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            if state is not None and state.get("pid") == process.pid:
                break
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
            try:
                _viewer_state_path(capture_ref, root=root).unlink()
            except FileNotFoundError:
                pass
            if attempt + 1 < VIEWER_START_ATTEMPTS:
                _wait_for_viewer_port(selected_port)
        if process is None or state is None or state.get("pid") != process.pid:
            previous = f" after stopping {len(stopped)} older viewer{'s' if len(stopped) != 1 else ''}" if stopped else ""
            raise JourneyViewError(
                f"The local Journey viewer could not bind 127.0.0.1:{selected_port}{previous}; "
                "choose another port with --port or PLAY_JOURNEY_PORT"
            )
    if open_browser:
        webbrowser.open(str(state["url"]))
    return state
