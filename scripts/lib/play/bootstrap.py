"""Transactional cross-harness bootstrap for Play and its Rote prerequisite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as platform_module
import queue
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .inbox_cache import public_cache_entries
from .harnesses import (
    HARNESS_BY_ID,
    HARNESS_SPECS,
    commands as harness_commands,
    detect_harness,
    labels as harness_labels,
    launch_surfaces,
    skill_roots as configured_skill_roots,
    supported_harnesses,
    target_ids,
)
from .identity import remember_login_provider, rote_session_status
from .recurrence import (
    RecurrenceError,
    enable_tulving as enable_tulving_support,
    probe_tulving,
)


SCHEMA = "play.bootstrap/v1"
PLAN_SCHEMA = "play.bootstrap-plan/v1"
REPORT_SCHEMA = "play.bootstrap-report/v1"
BACKUP_SCHEMA = "play.install-backup/v1"
BACKUP_CATALOG_SCHEMA = "play.install-backup-catalog/v1"
RESTORE_PLAN_SCHEMA = "play.install-restore-plan/v1"
RESTORE_REPORT_SCHEMA = "play.install-restore-report/v1"
BACKUP_RETENTION = 10
LOGIN_PROVIDERS = ("google", "github")
BROWSER_MODES = ("auto", "headed", "headless")
REMOTE_AUTH_EVIDENCE = "auth:remote-machine"
REGISTRY_NETWORK_MARKERS = (
    "network error",
    "error sending request",
    "failed to refresh session",
    "connection refused",
    "connection reset",
    "could not resolve host",
    "dns error",
    "name or service not known",
    "operation timed out",
    "timed out",
)
SUPPORTED_HARNESSES = supported_harnesses()
TARGET_IDS = target_ids()
HARNESS_COMMANDS = harness_commands()
LABELS = harness_labels()
HARNESS_LAUNCH = launch_surfaces()
ROTE_SKILL_PROVIDERS = {
    "codex": ("Codex", "CODEX_HOME", ".codex"),
    "claude-code": ("Claude Code", "CLAUDE_CONFIG_DIR", ".claude"),
    "agents-md": ("Shared .agents", "AGENTS_HOME", ".agents"),
    "cursor": ("Cursor", "CURSOR_CONFIG_DIR", ".cursor"),
    "kimi-code-cli": ("Kimi Code", "KIMI_CONFIG_DIR", ".kimi"),
    "hermes-agent": ("Hermes Agent", "HERMES_HOME", ".hermes"),
    "opencode": ("OpenCode", "OPENCODE_CONFIG_DIR", ".config/opencode"),
    "deepseek": ("DeepSeek Harness", "DSH_HOME", ".dsh"),
}
PLAY_MARKETPLACE = "play-skills"
PLAY_PLUGIN = "play@play-skills"
PLAY_REPOSITORY = "modiqo/play"
ROTE_MCP_LIFECYCLE_MINIMUM = (0, 69, 2)
ROTE_MCP_LIFECYCLE_MINIMUM_TEXT = ".".join(map(str, ROTE_MCP_LIFECYCLE_MINIMUM))
DEFAULT_SELECTED_HARNESSES = 3
MAX_PARALLEL_HARNESSES = 3
SETUP_PRO_TIPS = (
    "Rerun this installer to verify or repair an existing Play setup.",
    "Play snapshots owned state before every update or repair.",
    "Use arrow keys and Space to choose apps; setup runs up to three app jobs at once.",
    "Detailed receipts live under ~/.local/state/play-bootstrap/runs/.",
    "If verification fails, Play restores the previous verified state automatically.",
)
DOT_MATRIX_FRAMES = (
    "⠁",
    "⠃",
    "⠇",
    "⡇",
    "⣇",
    "⣧",
    "⣷",
    "⣿",
    "⣾",
    "⣼",
    "⣸",
    "⣰",
    "⣠",
    "⣀",
    "⢀",
)
DEFAULT_PROGRESS_HEARTBEAT_SECONDS = 0.12
DOT_MATRIX_BUSY_GLYPH = "⠿"
TERMINAL_CARD_WIDTH = 84


class BootstrapError(RuntimeError):
    """The bootstrap could not safely continue."""


@dataclass(frozen=True)
class HarnessTarget:
    id: str
    label: str
    command: str | None
    skill_roots: tuple[str, ...]
    rote_skills_installed: bool
    play_skill_installed: bool
    hooks: str
    score: int
    detected: bool
    selected: bool
    selection_reason: str


@dataclass(frozen=True)
class Step:
    id: str
    status: str
    detail: str
    command: list[str] | None = None
    target: str | None = None
    changed: bool = False
    evidence: str | None = None


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass
class ProgressToken:
    label: str
    started: float
    stop: threading.Event | None = None
    heartbeat: threading.Thread | None = None


class Progress:
    """Thread-safe install progress with stable and opt-in animated rendering."""

    def __init__(
        self,
        stream=None,
        *,
        enabled: bool = True,
        heartbeat_seconds: float = 0.0,
        interactive: bool | None = None,
        stable: bool = False,
        insights: Sequence[str] = (),
        insight_seconds: float = 4.0,
    ) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled
        self.heartbeat_seconds = max(0.0, heartbeat_seconds)
        if interactive is None:
            try:
                interactive = bool(self.stream.isatty())
            except (AttributeError, OSError):
                interactive = False
        self.interactive = interactive
        self.stable = stable
        self.insights = tuple(item.strip() for item in insights if item.strip())
        self.insight_seconds = max(0.001, insight_seconds)
        self._insight_offset = -1
        self._lock = threading.Lock()
        self._active: dict[int, ProgressToken] = {}
        self._line_visible = False
        self._frame = 0
        self._phase_label: str | None = None
        self._phase_started: float | None = None
        self._phase_completed = 0
        self._phase_failed = False

    def _clear_active_locked(self) -> None:
        if not self._line_visible:
            return
        self.stream.write("\r\033[2K")
        if self.insights:
            self.stream.write("\033[1A\r\033[2K")
        self.stream.flush()
        self._line_visible = False

    def _fit_terminal_line(self, text: str) -> str:
        width = max(20, shutil.get_terminal_size(fallback=(100, 24)).columns - 1)
        if len(text) <= width:
            return text
        return text[: max(1, width - 1)].rstrip() + "…"

    def _render_active_locked(self) -> None:
        if (
            not self.interactive
            or self.stable
            or (not self._active and self._phase_label is None)
        ):
            return
        now = time.monotonic()
        tokens = list(self._active.values())
        if not tokens:
            if self._phase_completed:
                text = (
                    f"{self._phase_label} · {self._phase_completed} "
                    f"step{'s' if self._phase_completed != 1 else ''} complete"
                )
            else:
                text = f"{self._phase_label} · starting"
        elif len(tokens) == 1:
            token = tokens[0]
            text = (
                f"{token.label} · {now - token.started:.1f}s"
                if self.heartbeat_seconds
                else token.label
            )
        else:
            labels = "; ".join(token.label for token in tokens)
            text = labels
            if self.heartbeat_seconds:
                elapsed = max(now - token.started for token in tokens)
                text = f"{text} · {elapsed:.1f}s"
        if self._phase_label is not None and tokens:
            text = f"{self._phase_label} · {text}"
        self._clear_active_locked()
        if self.insights:
            oldest = (
                min(token.started for token in tokens)
                if tokens
                else (self._phase_started or now)
            )
            rotation = int((now - oldest) // self.insight_seconds)
            insight = self.insights[(self._insight_offset + rotation) % len(self.insights)]
            self.stream.write(
                f"✦ {self._fit_terminal_line('Pro tip · ' + insight)}\r\n"
            )
        glyph = (
            DOT_MATRIX_FRAMES[self._frame % len(DOT_MATRIX_FRAMES)]
            if self.heartbeat_seconds
            else ("◆" if self._phase_label is not None else "›")
        )
        if self.heartbeat_seconds:
            self._frame += 1
        self.stream.write(f"{glyph} {self._fit_terminal_line(text)}")
        self.stream.flush()
        self._line_visible = True

    def _finish_phase_locked(self) -> None:
        if self._phase_label is None:
            return
        self._clear_active_locked()
        elapsed = time.monotonic() - (self._phase_started or time.monotonic())
        glyph = "✗" if self._phase_failed else "✓"
        count = self._phase_completed
        summary = f"{count} step{'s' if count != 1 else ''}"
        print(
            f"{glyph} {self._phase_label} · {summary} · {elapsed:.1f}s",
            file=self.stream,
            flush=True,
        )
        self._phase_label = None
        self._phase_started = None
        self._phase_completed = 0
        self._phase_failed = False

    def start_phase(self, label: str) -> None:
        """Group detailed terminal work under one calm, durable milestone."""

        if not self.enabled:
            return
        with self._lock:
            if self.interactive:
                self._finish_phase_locked()
                self._phase_label = label
                self._phase_started = time.monotonic()
                if self.stable:
                    print(
                        f"{DOT_MATRIX_BUSY_GLYPH} {label} · working",
                        file=self.stream,
                        flush=True,
                    )
                else:
                    self._render_active_locked()
            else:
                print(f"◆ {label}", file=self.stream, flush=True)

    def complete_phase(self) -> None:
        if not self.enabled or not self.interactive:
            return
        with self._lock:
            self._finish_phase_locked()

    def _refresh(self) -> None:
        if not self.enabled or not self.interactive:
            return
        with self._lock:
            self._render_active_locked()

    def begin(self, label: str) -> ProgressToken:
        token = ProgressToken(label, time.monotonic())
        if self.enabled:
            with self._lock:
                if self.interactive:
                    if not self._active:
                        self._insight_offset = (self._insight_offset + 1) % max(
                            1, len(self.insights)
                        )
                    self._active[id(token)] = token
                    if self.stable:
                        if self._phase_label is None:
                            print(
                                f"{DOT_MATRIX_BUSY_GLYPH} {label} · working",
                                file=self.stream,
                                flush=True,
                            )
                    else:
                        self._render_active_locked()
                else:
                    print(f"› {label}", file=self.stream, flush=True)
        if (
            self.enabled
            and self.interactive
            and not self.stable
            and self.heartbeat_seconds
        ):
            token.stop = threading.Event()

            def heartbeat() -> None:
                assert token.stop is not None
                while not token.stop.wait(self.heartbeat_seconds):
                    self._refresh()

            token.heartbeat = threading.Thread(target=heartbeat, daemon=True)
            token.heartbeat.start()
        return token

    def finish(self, token: ProgressToken, *, ok: bool = True) -> None:
        if token.stop is not None:
            token.stop.set()
        if token.heartbeat is not None:
            token.heartbeat.join(timeout=max(0.1, self.heartbeat_seconds * 2))
        elapsed = time.monotonic() - token.started
        if not self.enabled:
            return
        glyph = "✓" if ok else "✗"
        elapsed_text = (
            f" ({elapsed:.1f}s)"
            if elapsed >= 0.1 or self.heartbeat_seconds
            else ""
        )
        with self._lock:
            if self.interactive:
                self._active.pop(id(token), None)
                if not self.stable:
                    self._clear_active_locked()
                if self._phase_label is None:
                    print(
                        f"{glyph} {token.label}{elapsed_text}",
                        file=self.stream,
                        flush=True,
                    )
                else:
                    self._phase_completed += 1
                    self._phase_failed = self._phase_failed or not ok
                if not self.stable:
                    self._render_active_locked()
            else:
                print(f"{glyph} {token.label}{elapsed_text}", file=self.stream, flush=True)

    def call(self, label: str, operation: Callable[[], Any]) -> Any:
        token = self.begin(label)
        try:
            result = operation()
        except KeyboardInterrupt:
            self.finish(token, ok=False)
            raise
        except Exception:
            self.finish(token, ok=False)
            raise
        self.finish(token)
        return result

    def command(
        self, label: str, runner: Runner, command: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        token = self.begin(label)
        try:
            result = runner(command)
        except KeyboardInterrupt:
            self.finish(token, ok=False)
            raise
        except Exception:
            self.finish(token, ok=False)
            raise
        self.finish(token, ok=result.returncode == 0)
        return result


def _progress(progress: Progress | None) -> Progress:
    return progress if progress is not None else Progress(enabled=False)


def _installer_progress() -> Progress:
    animate = os.environ.get("PLAY_INSTALL_ANIMATE") == "1"
    return Progress(
        enabled=os.environ.get("PLAY_INSTALL_QUIET") != "1",
        heartbeat_seconds=(DEFAULT_PROGRESS_HEARTBEAT_SECONDS if animate else 0.0),
        stable=not animate,
    )


def _parallel_harness_work(
    harnesses: Sequence[str], operation: Callable[[str], Any]
) -> dict[str, Any]:
    """Run independent harness work concurrently and return deterministic keyed results."""

    ordered = list(dict.fromkeys(harnesses))
    if not ordered:
        return {}
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_HARNESSES, len(ordered))) as executor:
        futures = {harness: executor.submit(operation, harness) for harness in ordered}
        return {harness: futures[harness].result() for harness in ordered}


def _home() -> Path:
    return Path.home()


def _require_supported_os(
    *, platform: str | None = None, os_name: str | None = None
) -> None:
    """Reject untested native Windows while allowing Linux-based WSL."""

    detected_platform = sys.platform if platform is None else platform
    detected_os_name = os.name if os_name is None else os_name
    if detected_os_name == "nt" or detected_platform.startswith("win"):
        raise BootstrapError(
            "native Windows is not supported yet; run Play from WSL2, Linux, or macOS"
        )


def _linux_release() -> dict[str, str]:
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _os_snapshot() -> dict[str, Any]:
    """Return a stable, human-readable operating-system receipt."""

    system = platform_module.system() or "Unknown"
    release = platform_module.release() or "unknown"
    architecture = platform_module.machine() or "unknown"
    if architecture.lower() in {"aarch64", "arm64"}:
        architecture = "arm64"
    elif architecture.lower() in {"amd64", "x86_64"}:
        architecture = "x86_64"

    family = system.lower()
    name = system
    version = release
    distribution: str | None = None
    wsl = False
    wsl_version: int | None = None
    if system == "Darwin":
        family = "macos"
        name = "macOS"
        version = platform_module.mac_ver()[0] or release
    elif system == "Linux":
        release_values = _linux_release()
        distribution = release_values.get("PRETTY_NAME") or release_values.get("NAME")
        name = distribution or "Linux"
        version = release_values.get("VERSION_ID") or release
        release_lower = release.lower()
        wsl = bool(
            os.environ.get("WSL_DISTRO_NAME")
            or os.environ.get("WSL_INTEROP")
            or "microsoft" in release_lower
        )
        if wsl:
            wsl_version = (
                2
                if "wsl2" in release_lower or "microsoft-standard" in release_lower
                else 1
            )
            name = f"WSL{wsl_version}"

    if wsl:
        display_parts = [name]
        if distribution:
            display_parts.append(distribution)
    else:
        display_parts = [name]
        if version and version.lower() not in name.lower():
            display_parts.append(version)
    display_parts.append(architecture)
    return {
        "family": family,
        "name": name,
        "version": version,
        "architecture": architecture,
        "distribution": distribution,
        "wsl": wsl,
        "wsl_version": wsl_version,
        "display": " · ".join(display_parts),
    }


def _play_version() -> str:
    return (Path(__file__).resolve().parents[3] / "VERSION").read_text(
        encoding="utf-8"
    ).strip()


def _installed_play_version() -> str | None:
    candidate = _portable_play_path() / "VERSION"
    try:
        version = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return version or None


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _managed_launcher_paths() -> tuple[Path, ...]:
    home = _home()
    return (
        Path(
            os.environ.get(
                "PLAY_MACHINE_LAUNCHER", home / ".local" / "bin" / "play-machine"
            )
        ).expanduser(),
        Path(
            os.environ.get(
                "PLAY_ROUTING_LAUNCHER", home / ".local" / "bin" / "play-routing"
            )
        ).expanduser(),
        Path(
            os.environ.get(
                "PLAY_JOURNEY_LAUNCHER", home / ".local" / "bin" / "play-journey"
            )
        ).expanduser(),
        Path(
            os.environ.get("PLAY_CLI_LAUNCHER", home / ".local" / "bin" / "play")
        ).expanduser(),
    )


def _play_update_snapshot() -> dict[str, Any]:
    installed = _installed_play_version()
    target = _play_version()
    portable = _portable_play_path()
    required_portable = (
        portable / ".play-install.json",
        portable / "SKILL.md",
        portable / "VERSION",
        portable / "scripts" / "harness" / "install-all",
        portable / "scripts" / "harness" / "play-profile",
        portable / "scripts" / "bin" / "play-bootstrap",
        portable / "scripts" / "bin" / "play-machine",
        portable / "scripts" / "bin" / "play-preflight",
        portable / "scripts" / "bin" / "play-digest",
    )
    managed_runtime = (*_managed_launcher_paths(), _activation_profile_state_path())
    installed_skill_paths = tuple(
        root / "play" for roots in _roots().values() for root in roots
    )
    existing_state = any(
        _path_present(path)
        for path in (portable, *managed_runtime, *installed_skill_paths)
    )
    missing_paths = [
        str(path)
        for path in (*required_portable, *managed_runtime)
        if not _path_present(path)
    ]

    if not existing_state:
        install_state = "fresh"
        health = "clean"
        status = "not_installed"
        detail = f"Play {target} will be installed."
        recommended_action = "install"
        missing_paths = []
    elif installed is not None and installed != target:
        install_state = "update"
        health = "outdated"
        status = "available"
        detail = f"Play {target} will replace {installed} after a recovery snapshot."
        recommended_action = "update"
    elif installed == target and not missing_paths:
        install_state = "verify"
        health = "current"
        status = "current"
        detail = f"Play {installed} is current and will be verified."
        recommended_action = "verify"
    else:
        install_state = "repair"
        health = "damaged"
        status = "repair_required"
        missing_count = len(missing_paths)
        detail = (
            f"Play {target} will repair {missing_count} missing managed "
            f"item{'s' if missing_count != 1 else ''} after a recovery snapshot."
        )
        recommended_action = "repair"
    return {
        "installed_version": installed,
        "target_version": target,
        "update_status": status,
        "install_state": install_state,
        "health": health,
        "existing_state": existing_state,
        "missing_paths": missing_paths,
        "detail": detail,
        "recommended_action": recommended_action,
    }


def _roots() -> dict[str, tuple[Path, ...]]:
    return {
        spec.id: configured_skill_roots(spec, home=_home())
        for spec in HARNESS_SPECS
    }


def _has_skill(root: Path, kind: str) -> bool:
    if kind == "play":
        return (root / "play" / "SKILL.md").is_file()
    try:
        return any(
            (child.name == "rote" or child.name.startswith("rote-"))
            and (child / "SKILL.md").is_file()
            for child in root.iterdir()
        )
    except OSError:
        return False


def resolve_rote() -> str | None:
    if executable := shutil.which("rote"):
        return executable
    for candidate in (_home() / ".local" / "bin" / "rote", _home() / ".cargo" / "bin" / "rote"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), text=True, capture_output=True, check=False, timeout=900
    )


def _official_rote_install_command() -> list[str]:
    return [
        "bash",
        "-c",
        'ROTE_YES=1 ROTE_FULL=1 bash -c "$(curl --proto \'=https\' --tlsv1.2 -fsSL https://getrote.dev/install)" </dev/null',
    ]


def _run_visible(
    command: Sequence[str], runner: Runner
) -> subprocess.CompletedProcess[str]:
    """Let long interactive installers own the terminal while preserving test injection."""

    if runner is not run:
        return runner(command)
    completed = subprocess.run(
        list(command),
        text=True,
        check=False,
        timeout=900,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        stdout="",
        stderr="",
    )


def _run_login_visible(
    command: Sequence[str],
    runner: Runner,
    *,
    stream: Any = None,
) -> subprocess.CompletedProcess[str]:
    """Stream OAuth guidance while retaining Rote's typed tail for diagnostics.

    Browser-opening guidance must remain live, but the terminal-oriented
    ``@@status``/``@@result`` envelope is machine evidence rather than setup UI.
    Once that envelope begins, keep it in the returned receipt without echoing
    it between Play progress lines.
    """

    if runner is not run:
        return runner(command)
    output_stream = stream if stream is not None else sys.stderr
    process = subprocess.Popen(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    stdout = process.stdout
    assert stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()

    def read_lines() -> None:
        try:
            for line in stdout:
                lines.put(line)
        finally:
            stdout.close()
            lines.put(None)

    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()
    captured: list[str] = []
    typed_envelope = False
    deadline = time.monotonic() + 900
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            process.wait()
            raise subprocess.TimeoutExpired(list(command), 900)
        try:
            line = lines.get(timeout=min(0.25, remaining))
        except queue.Empty:
            continue
        if line is None:
            break
        captured.append(line)
        if line.strip().startswith("@@status"):
            typed_envelope = True
        if not typed_envelope:
            print(line, end="", file=output_stream, flush=True)
    returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    reader.join(timeout=1)
    return subprocess.CompletedProcess(
        list(command), returncode, stdout="".join(captured), stderr=""
    )


def _probe_version(rote: str | None, runner: Runner) -> str | None:
    if rote is None:
        return None
    result = runner([rote, "version"])
    text = (result.stdout or result.stderr).strip()
    for line in text.splitlines():
        if line.startswith("version:"):
            return line.partition(":")[2].strip()
    return text or None


def _parse_semantic_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _rote_compatibility_step(rote: str, runner: Runner) -> Step:
    version = _probe_version(rote, runner)
    parsed = _parse_semantic_version(version)
    command = [rote, "version"]
    if parsed is None:
        return Step(
            "verify_rote_compatibility",
            "failed",
            "Play could not verify the installed Rote version. "
            f"Rote {ROTE_MCP_LIFECYCLE_MINIMUM_TEXT} or newer is required for safe in-place MCP reauthorization.",
            command=command,
        )
    if parsed < ROTE_MCP_LIFECYCLE_MINIMUM:
        return Step(
            "verify_rote_compatibility",
            "failed",
            f"Rote {version} is too old. Play requires Rote "
            f"{ROTE_MCP_LIFECYCLE_MINIMUM_TEXT} or newer so MCP credentials can be reauthorized "
            "without deleting or rebuilding the adapter. Run `rote self-update --yes`, then retry.",
            command=command,
        )
    return Step(
        "verify_rote_compatibility",
        "unchanged",
        f"Rote {version} supports stable MCP identity and in-place credential reauthorization.",
        command=command,
    )


def _probe_identity(rote: str | None, runner: Runner) -> str:
    if rote is None:
        return "unavailable"
    result = runner([rote, "whoami", "--check"])
    return rote_session_status(result)


def _registry_network_failure(result: subprocess.CompletedProcess[str]) -> bool:
    output = "\n".join(
        part for part in (result.stdout, result.stderr) if part
    ).lower()
    return any(marker in output for marker in REGISTRY_NETWORK_MARKERS)


def _registry_network_blocker(action: str) -> str:
    return (
        f"{action} could not reach the Rote registry. Run setup from a normal terminal "
        "with network access. If an agent launched setup, allow network access in the "
        "Codex sandbox or permit the command in Claude Code, then retry."
    )


def _registry_credentials_blocker() -> str:
    return (
        "Rote registry credentials are required before Play can be installed. "
        "On a machine with a browser, choose Google or GitHub. On a headless "
        "machine, authenticate Rote with `rote provision` and `rote claim`, then retry. "
        "For unattended browser sign-in, set PLAY_LOGIN_PROVIDER=google or github."
    )


def _remote_auth_guidance() -> str:
    return (
        "No browser session was detected. On a machine with a browser, run "
        "`rote login --provider google` or `rote login --provider github`, then "
        "`rote provision --ttl 30`. On this machine, run `rote claim <dxp_...>`, "
        "verify with `rote whoami --check`, and rerun the Play installer. Treat the claim "
        "token as a password; Play did not receive or record it."
    )


def _browser_mode(
    requested: str = "auto",
    *,
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
) -> str:
    """Resolve whether this process can reasonably launch a graphical browser."""

    if requested not in BROWSER_MODES:
        raise BootstrapError(
            f"browser mode must be one of: {', '.join(BROWSER_MODES)}"
        )
    if requested != "auto":
        return requested
    environment = os.environ if environ is None else environ
    platform_name = platform_module.system() if system is None else system
    if any(environment.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY")):
        return "headed"
    if platform_name == "Linux" or any(
        environment.get(name) for name in ("SSH_TTY", "SSH_CONNECTION")
    ):
        return "headless"
    return "headed"


def _identity_gate(
    rote: str,
    *,
    login_provider: str | None,
    remote_auth: bool = False,
    runner: Runner,
) -> tuple[Step, bool]:
    """Verify identity or complete one explicit OAuth provider flow before setup mutates Play."""

    identity = runner([rote, "whoami", "--check"])
    identity_status = rote_session_status(identity)
    if identity_status == "authenticated":
        return Step("rote_identity", "completed", "Rote identity verified."), True
    if identity_status == "error":
        detail = (
            _registry_network_blocker("Rote identity check")
            if _registry_network_failure(identity)
            else "Rote identity check failed without declaring that login is required."
        )
        raise BootstrapError(detail)
    if remote_auth:
        return (
            Step(
                "rote_identity",
                "onboarding_required",
                _remote_auth_guidance(),
                command=[rote, "claim", "<provision-token>"],
                evidence=REMOTE_AUTH_EVIDENCE,
            ),
            False,
        )
    if login_provider is None:
        raise BootstrapError(_registry_credentials_blocker())
    if login_provider not in LOGIN_PROVIDERS:
        raise BootstrapError(
            f"login provider must be one of: {', '.join(LOGIN_PROVIDERS)}"
        )
    command = [rote, "login", "--provider", login_provider]
    result = _run_login_visible(command, runner)
    if result.returncode != 0:
        detail = (
            _registry_network_blocker("Rote sign-in")
            if _registry_network_failure(result)
            else (
                f"{login_provider.title()} sign-in did not complete. "
                "Retry setup or choose the other provider."
            )
        )
        return (
            Step(
                "rote_identity",
                "onboarding_required",
                detail,
                command=command,
            ),
            False,
        )
    identity = runner([rote, "whoami", "--check"])
    identity_output = (identity.stdout or identity.stderr).strip()
    email_match = re.search(r"(?im)^ok:\s*([^@\s]+@[^@\s]+\.[^@\s]+)\s*$", identity_output)
    if rote_session_status(identity) != "authenticated":
        detail = (
            _registry_network_blocker("Rote identity verification")
            if _registry_network_failure(identity)
            else (
                f"{login_provider.title()} sign-in returned without a verified "
                "Rote identity."
            )
        )
        return (
            Step(
                "rote_identity",
                "onboarding_required",
                detail,
                command=command,
            ),
            False,
        )
    remember_login_provider(login_provider)
    detail = f"Signed in with {login_provider.title()}."
    if email_match is not None:
        detail = (
            f"Signed in with {login_provider.title()} as "
            f"{email_match.group(1).lower()}."
        )
    return (
        Step(
            "rote_identity",
            "completed",
            detail,
            command=command,
            changed=True,
        ),
        True,
    )


def _probe_update(rote: str | None, runner: Runner) -> dict[str, Any]:
    if rote is None:
        return {
            "status": "not_installed",
            "detail": "Rote is not installed.",
            "recommended_action": "install",
            "check_command": None,
        }
    command = [rote, "self-update", "--check"]
    result = runner(command)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return {
            "status": "check_failed",
            "detail": output or f"update check exited {result.returncode}",
            "recommended_action": "review",
            "check_command": command,
        }
    normalized = output.lower()
    current_markers = (
        "latest version",
        "already current",
        "up to date",
        "up-to-date",
        "no update available",
        "rote is current",
    )
    current = any(marker in normalized for marker in current_markers)
    return {
        "status": "current" if current else "available",
        "detail": output or "Rote reports that an update is available.",
        "recommended_action": "keep" if current else "update",
        "check_command": command,
    }


def _rote_snapshot(runner: Runner, *, check_update: bool = True) -> dict[str, Any]:
    rote = resolve_rote()
    snapshot = {
        "path": rote,
        "version": _probe_version(rote, runner),
        "identity": _probe_identity(rote, runner),
    }
    if check_update:
        snapshot["update"] = _probe_update(rote, runner)
    return snapshot


def _rote_skill_roots() -> dict[str, tuple[str, Path]]:
    roots: dict[str, tuple[str, Path]] = {}
    for provider, (label, variable, default) in ROTE_SKILL_PROVIDERS.items():
        home = Path(os.environ.get(variable, _home() / default)).expanduser()
        roots[provider] = (label, home / "skills")
    return roots


def prepare_selected_skill_roots(selected: Sequence[str]) -> Step:
    """Create only the personal skill roots required by selected harnesses."""
    roots = _rote_skill_roots()
    created: list[str] = []
    present: list[str] = []
    for harness in dict.fromkeys(selected):
        provider = TARGET_IDS.get(harness)
        if provider is None or provider not in roots:
            return Step(
                "prepare_harness_skill_roots",
                "failed",
                f"No personal skill root is defined for selected harness {harness!r}.",
            )
        label, root = roots[provider]
        existed = root.is_dir()
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as error:
            return Step(
                "prepare_harness_skill_roots",
                "failed",
                f"Could not prepare {label} skill root {root}: {error}",
            )
        if not root.is_dir():
            return Step(
                "prepare_harness_skill_roots",
                "failed",
                f"The {label} skill root is not a directory: {root}",
            )
        (present if existed else created).append(f"{label}: {root}")

    details: list[str] = []
    if created:
        details.append("created " + ", ".join(created))
    if present:
        details.append("already present " + ", ".join(present))
    return Step(
        "prepare_harness_skill_roots",
        "completed" if created else "unchanged",
        "; ".join(details) or "No harness skill roots were selected.",
        changed=bool(created),
    )


def _rote_skills_snapshot(providers: Sequence[str] | None = None) -> list[dict[str, Any]]:
    result = []
    roots = _rote_skill_roots()
    names = list(dict.fromkeys(providers or roots.keys()))
    for provider in names:
        label, root = roots[provider]
        try:
            names = sorted(
                child.name
                for child in root.iterdir()
                if (child.name == "rote" or child.name.startswith("rote-"))
                and (child / "SKILL.md").is_file()
            )
        except OSError:
            names = []
        installed = bool(names)
        result.append(
            {
                "provider": provider,
                "label": label,
                "root": str(root),
                "installed": installed,
                "skill_count": len(names),
                "skills": names,
                "recommended_action": "refresh" if installed else "install",
            }
        )
    return result


def _rote_skill_command(rote: str, selected: Sequence[str]) -> list[str]:
    command = [rote, "install", "skill"]
    for target in dict.fromkeys(TARGET_IDS[name] for name in selected):
        command.extend(["--target", target])
    command.extend(["--personal", "--package", "*", "--force"])
    return command


def _rote_skill_harnesses(
    selected: Sequence[str], skill_snapshot: Sequence[dict[str, Any]], update_status: str
) -> list[str]:
    """Refresh all targets after a Rote update; otherwise install only missing providers."""

    if update_status == "available":
        return list(dict.fromkeys(selected))
    missing = {
        str(item.get("provider"))
        for item in skill_snapshot
        if isinstance(item, dict) and not item.get("installed")
    }
    return [name for name in dict.fromkeys(selected) if TARGET_IDS[name] in missing]


def discover_targets(*, top_k: int, requested: Sequence[str] | None = None) -> list[HarnessTarget]:
    if top_k < 1:
        raise BootstrapError("top-k must be at least 1")
    unknown = sorted(set(requested or ()) - set(SUPPORTED_HARNESSES))
    if unknown:
        raise BootstrapError("unsupported harness name(s): " + ", ".join(unknown))
    requested_unique = list(dict.fromkeys(requested or ()))

    candidates: list[dict[str, Any]] = []
    for order, name in enumerate(SUPPORTED_HARNESSES):
        spec = HARNESS_BY_ID[name]
        roots = _roots()[name]
        present, command = detect_harness(spec, resolver=shutil.which, home=_home())
        rote_ready = any(_has_skill(root, "rote") for root in roots)
        play_ready = any(_has_skill(root, "play") for root in roots)
        score = (100 if command else 0) + (30 if rote_ready else 0) + (20 if play_ready else 0) + (10 - order)
        candidates.append(
            {
                "id": name,
                "label": LABELS[name],
                "command": command,
                "skill_roots": tuple(str(root) for root in roots),
                "rote_skills_installed": rote_ready,
                "play_skill_installed": play_ready,
                "hooks": (
                    "managed"
                    if spec.hook_style in {"nested-json", "flat-json"}
                    else "not_required"
                ),
                "score": score,
                "detected": present,
                "present": present,
            }
        )
    if requested_unique:
        selected = {
            str(item["id"])
            for item in candidates
            if item["present"] and item["id"] in requested_unique
        }
    else:
        ranked = sorted(
            (item for item in candidates if item["present"]),
            key=lambda item: (-int(item["score"]), SUPPORTED_HARNESSES.index(str(item["id"]))),
        )
        selected = {str(item["id"]) for item in ranked[:top_k]}
    return [
        HarnessTarget(
            **{key: value for key, value in item.items() if key != "present"},
            selected=item["id"] in selected,
            selection_reason=(
                "explicitly selected"
                if requested_unique and item["id"] in selected
                else (
                    "requested but not detected"
                    if requested_unique and item["id"] in requested_unique
                    else (
                        f"selected in top {top_k}"
                        if item["id"] in selected
                        else ("not detected" if not item["present"] else f"outside top {top_k}")
                    )
                )
            ),
        )
        for item in candidates
    ]


def _decode_harness_picker_key(sequence: bytes) -> str:
    if sequence in {b"\x1b[A", b"\x1bOA"}:
        return "up"
    if sequence in {b"\x1b[B", b"\x1bOB"}:
        return "down"
    if sequence in {b"\r", b"\n"}:
        return "confirm"
    if sequence == b" ":
        return "toggle"
    if sequence.lower() == b"q" or sequence in {b"\x04", b"\x1b"}:
        return "cancel"
    if sequence.lower() in {b"k", b"w"}:
        return "up"
    if sequence.lower() in {b"j", b"s"} or sequence == b"\t":
        return "down"
    if sequence.lower() == b"a":
        return "all"
    if sequence.lower() == b"c":
        return "clear"
    return "unknown"


def _read_harness_picker_key(file_descriptor: int) -> str:
    import select

    first = os.read(file_descriptor, 1)
    if not first:
        return "cancel"
    sequence = first
    if first == b"\x1b":
        for _ in range(2):
            readable, _, _ = select.select([file_descriptor], [], [], 0.05)
            if not readable:
                break
            sequence += os.read(file_descriptor, 1)
    return _decode_harness_picker_key(sequence)


def _update_harness_picker(
    key: str,
    detected: Sequence[HarnessTarget],
    selected: Sequence[str],
    active_index: int,
) -> tuple[int, list[str], str | None, str | None]:
    current = list(
        dict.fromkeys(selected)
    )
    if not detected:
        return 0, current, "cancel", None
    active_index = max(0, min(active_index, len(detected) - 1))
    if key == "up":
        active_index = (active_index - 1) % len(detected)
    elif key == "down":
        active_index = (active_index + 1) % len(detected)
    elif key == "toggle":
        harness = detected[active_index].id
        if harness in current:
            current.remove(harness)
        else:
            current.append(harness)
    elif key == "all":
        current = [target.id for target in detected]
    elif key == "clear":
        current = []
    elif key == "cancel":
        return active_index, current, "cancel", None
    elif key == "confirm":
        if current:
            return active_index, current, "confirm", None
        return active_index, current, None, "Choose at least one app before continuing."
    elif key == "unknown":
        return active_index, current, None, "Use arrow keys, Space, Enter, or q."
    detected_order = {target.id: index for index, target in enumerate(detected)}
    current.sort(key=detected_order.__getitem__)
    return active_index, current, None, None


def _fit_picker_line(line: str, width: int | None) -> str:
    if width is None or len(line) <= width:
        return line
    if width <= 1:
        return line[:width]
    return line[: width - 1] + "…"


def _render_harness_picker(
    detected: Sequence[HarnessTarget],
    selected: Sequence[str] | None = None,
    *,
    active_index: int = 0,
    message: str | None = None,
    width: int | None = None,
) -> str:
    checked = set(
        selected
        if selected is not None
        else [target.id for target in detected if target.selected]
    )
    lines = [
        "",
        "  Select harnesses",
        "",
        "  The checked apps are recommended from this machine's detected setup.",
        "  Use ↑/↓ to move, Space to toggle, and Enter to continue.",
        "",
    ]
    for index, target in enumerate(detected):
        spec = HARNESS_BY_ID[target.id]
        checkbox = "✓" if target.id in checked else " "
        pointer = "❯" if index == active_index else " "
        recommendation = "  recommended" if target.selected else ""
        lines.append(
            f"  {pointer} [{checkbox}] {spec.glyph} {target.label:<26} {spec.play_entry}{recommendation}"
        )
    shared_labels = [
        spec.label for spec in HARNESS_SPECS if "agents" in spec.skill_sources
    ]
    lines.extend(
        [
            "",
            "  Shared skills: ~/.agents/skills",
            f"  Used by: {', '.join(shared_labels)}",
            "  Play updates only Play-owned entries in that shared root.",
            "",
            (
                f"  {message}"
                if message
                else f"  {len(checked)} checked · a selects all · c clears · q cancels"
            ),
        ]
    )
    return "\n".join(_fit_picker_line(line, width) for line in lines)


def _redraw_harness_picker(
    output: Any,
    frame: str,
    previous_line_count: int,
) -> int:
    lines = frame.split("\n")
    if previous_line_count:
        output.write(f"\x1b[{previous_line_count}A")
    for line in lines:
        output.write(f"\r\x1b[2K{line}\n")
    for _ in range(max(0, previous_line_count - len(lines))):
        output.write("\r\x1b[2K\n")
    output.flush()
    return len(lines)


def _run_harness_picker(
    detected: Sequence[HarnessTarget],
    stream: Any,
    output: Any,
) -> list[str]:
    import termios
    import tty

    file_descriptor = stream.fileno()
    try:
        terminal_state = termios.tcgetattr(file_descriptor)
    except termios.error as error:
        raise BootstrapError(
            "harness selection needs a terminal with arrow-key support; "
            "automation must pass --harness or set PLAY_INSTALL_YES=1"
        ) from error
    try:
        width = max(20, os.get_terminal_size(output.fileno()).columns - 1)
    except (AttributeError, OSError):
        width = max(20, shutil.get_terminal_size(fallback=(100, 24)).columns - 1)
    selected = [target.id for target in detected if target.selected]
    active_index = 0
    message = None
    previous_line_count = 0
    output.write("\x1b[?25l")
    output.flush()
    try:
        tty.setcbreak(file_descriptor)
        while True:
            frame = _render_harness_picker(
                detected,
                selected,
                active_index=active_index,
                message=message,
                width=width,
            )
            previous_line_count = _redraw_harness_picker(
                output, frame, previous_line_count
            )
            key = _read_harness_picker_key(file_descriptor)
            active_index, selected, outcome, message = _update_harness_picker(
                key, detected, selected, active_index
            )
            if outcome == "confirm":
                final_frame = _render_harness_picker(
                    detected,
                    selected,
                    active_index=active_index,
                    message=f"✓ {len(selected)} apps selected.",
                    width=width,
                )
                _redraw_harness_picker(output, final_frame, previous_line_count)
                return selected
            if outcome == "cancel":
                return []
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, terminal_state)
        output.write("\x1b[?25h")
        output.flush()


def _missing_harness_advisory(requested: Sequence[str] | None = None) -> str:
    requested_labels = [
        LABELS[name]
        for name in dict.fromkeys(requested or ())
        if name in LABELS
    ]
    if requested_labels:
        opening = (
            "Play could not find the selected harnesses on PATH: "
            + ", ".join(requested_labels)
            + "."
        )
    else:
        opening = "Play could not find a supported harness on PATH."
    return "\n".join(
        [
            opening,
            "Play supports Linux, including Ubuntu.",
            "",
            "Install Codex, Claude Code, or another supported harness first.",
            "Run these commands as your normal user, without sudo.",
            "",
            "Install Codex:",
            "  curl -fsSL https://chatgpt.com/codex/install.sh | sh",
            "",
            "Install Claude Code:",
            "  curl -fsSL https://claude.ai/install.sh | bash",
            "",
            "Open a new terminal, then verify the harnesses you installed:",
            "  command -v codex && codex --version",
            "  command -v claude && claude --version",
            "",
            "Retry Play and let it detect the installed harnesses:",
            "  curl -fsSL https://getrote.dev/playoffs/install.sh | sh",
            "",
            "To select both explicitly, repeat --harness:",
            "  curl -fsSL https://getrote.dev/playoffs/install.sh \\",
            "    | sh -s -- --harness codex --harness claude",
            "",
            "The --harness option selects an installed harness. It does not install one.",
        ]
    )


def _choose_detected_harnesses(*, top_k: int) -> list[str]:
    detected = [
        target
        for target in discover_targets(top_k=top_k)
        if target.detected
    ]
    if not detected:
        raise BootstrapError(_missing_harness_advisory())
    stream = None
    close_stream = False
    output = sys.stderr
    if sys.stdin.isatty():
        stream = sys.stdin
        if not output.isatty():
            output = stream
    else:
        try:
            stream = open("/dev/tty", "r+", encoding="utf-8")
            output = stream
            close_stream = True
        except OSError as error:
            raise BootstrapError(
                "harness selection needs an interactive terminal; CI must pass "
                "--harness or set PLAY_INSTALL_YES=1"
            ) from error
    try:
        return _run_harness_picker(detected, stream, output)
    finally:
        if close_stream:
            stream.close()


def _shared_agents_plan(selected: Sequence[str]) -> dict[str, Any]:
    targets = [
        harness
        for harness in selected
        if "agents" in HARNESS_BY_ID[harness].skill_sources
    ]
    root = Path(
        os.environ.get("AGENTS_HOME", _home() / ".agents")
    ).expanduser()
    return {
        "path": str(root / "skills"),
        "targets": targets,
        "will_create": bool(targets) and not (root / "skills").is_dir(),
        "preserves_unrelated_entries": True,
    }


def build_plan(
    *, top_k: int = 3, requested: Sequence[str] | None = None, runner: Runner = run
) -> dict[str, Any]:
    targets = discover_targets(top_k=top_k, requested=requested)
    recovery_catalog = list_play_backups()
    selected = [target.id for target in targets if target.selected]
    if not selected:
        raise BootstrapError(_missing_harness_advisory(requested))
    if "codex" in selected:
        # Fail before identity, cache, backup, or harness mutations. The same
        # parser protects later Codex enablement and rollback operations.
        codex_disabled_play_entries()
    shared_agents = _shared_agents_plan(selected)
    play_state = _play_update_snapshot()
    play_install_state = str(play_state["install_state"])
    install_effects = {
        "fresh": "installs Play-owned state while preserving unrelated harness settings",
        "verify": "keeps byte-current Play files in place, repairs drift if found, and verifies every selected harness",
        "update": "replaces the older Play version after a recovery snapshot while preserving unrelated harness settings",
        "repair": "backs up the damaged Play state, restores missing managed files, and preserves unrelated harness settings",
    }
    tulving = probe_tulving(resolver=shutil.which, check_update=True)
    rote_state = _rote_snapshot(runner)
    rote = rote_state["path"]
    update = rote_state["update"]
    if rote is None:
        rote_action = {
            "id": "install_rote",
            "effect": "downloads and installs executable code",
            "approval_required": True,
            "recommended": True,
        }
    elif update["status"] == "available":
        rote_action = {
            "id": "update_rote",
            "effect": update["detail"],
            "command": ["rote", "self-update", "--yes"],
            "recommended": True,
        }
    elif update["status"] == "current":
        rote_action = {
            "id": "keep_rote_current",
            "effect": update["detail"],
            "recommended": False,
        }
    else:
        rote_action = {
            "id": "review_rote_update",
            "effect": f"Update availability could not be determined: {update['detail']}",
            "recommended": False,
        }
    tulving_update = tulving.get("update", {})
    if tulving.get("available") is not True:
        tulving_action = {
            "id": "install_tulving",
            "effect": "installs Tulving and initializes its clock after Play verification",
            "approval_required": True,
            "recommended": False,
        }
    elif isinstance(tulving_update, dict) and tulving_update.get("status") == "available":
        tulving_action = {
            "id": "update_tulving",
            "effect": str(tulving_update.get("detail") or "updates Tulving"),
            "command": ["tulving", "update"],
            "approval_required": True,
            "recommended": False,
        }
    elif tulving.get("ready") is not True:
        tulving_action = {
            "id": "initialize_tulving",
            "effect": "initializes Tulving's clock after Play verification",
            "approval_required": True,
            "recommended": False,
        }
    elif isinstance(tulving_update, dict) and tulving_update.get("status") == "check_failed":
        tulving_action = {
            "id": "review_tulving_update",
            "effect": str(tulving_update.get("detail") or "Tulving update check failed"),
            "recommended": False,
        }
    else:
        tulving_action = {
            "id": "keep_tulving_current",
            "effect": str(tulving_update.get("detail") or "Tulving is current"),
            "recommended": False,
        }
    rote_targets = list(dict.fromkeys(TARGET_IDS[name] for name in selected))
    rote_skills = _rote_skills_snapshot(rote_targets)
    missing_skill_roots = [item["provider"] for item in rote_skills if not item["installed"]]
    existing_skill_roots = [item["provider"] for item in rote_skills if item["installed"]]
    skill_harnesses = _rote_skill_harnesses(selected, rote_skills, update["status"])
    targeted_skill_providers = {TARGET_IDS[name] for name in skill_harnesses}
    rote_skills = [
        {
            **item,
            "recommended_action": (
                "refresh" if item["installed"] else "install"
            ) if item["provider"] in targeted_skill_providers else "keep",
        }
        for item in rote_skills
    ]
    portable_hook_targets = [
        target.id
        for target in targets
        if target.selected
        and target.hooks == "managed"
    ]
    actions = [
        rote_action,
        tulving_action,
        {
            "id": "verify_rote_identity",
            "effect": "requires an authenticated Rote identity before changing Play-owned state; headless machines can claim credentials provisioned elsewhere",
            "recommended": True,
        },
        {
            "id": "warm_public_play_cache",
            "effect": "builds and verifies a canonical seven-day public Play snapshot for What’s New",
            "recommended": True,
        },
        {
            "id": "prepare_harness_skill_roots",
            "effect": "creates missing personal skill directories only for detected and selected harnesses",
            "targets": selected,
            "recommended": True,
        },
        {
            "id": "prepare_shared_agents_root",
            "effect": (
                f"creates or updates {shared_agents['path']} for compatible selected harnesses while preserving unrelated entries"
            ),
            "targets": shared_agents["targets"],
            "recommended": bool(shared_agents["targets"]),
        },
        {
            "id": "converge_rote_skills",
            "effect": (
                "installs missing or updated bundled Rote skills in personal harness roots"
                if skill_harnesses
                else "keeps current Rote skills unchanged"
            ),
            "missing_providers": missing_skill_roots,
            "refresh_providers": existing_skill_roots,
            "targets": skill_harnesses,
            "command": _rote_skill_command("rote", skill_harnesses) if skill_harnesses else None,
            "recommended": bool(skill_harnesses),
        },
        {
            "id": "converge_play_marketplaces",
            "effect": "verifies the selected Play version in Codex and Claude, replacing only missing or byte-stale plugins after backup",
            "targets": [name for name in selected if name in {"codex", "claude"}],
            "commands": {
                "codex": [
                    ["codex", "plugin", "marketplace", "upgrade", PLAY_MARKETPLACE],
                    ["codex", "plugin", "remove", PLAY_PLUGIN],
                    ["codex", "plugin", "add", PLAY_PLUGIN],
                ],
                "claude": [
                    ["claude", "plugin", "marketplace", "update", PLAY_MARKETPLACE],
                    ["claude", "plugin", "uninstall", PLAY_PLUGIN, "--scope", "user"],
                    ["claude", "plugin", "install", PLAY_PLUGIN, "--scope", "user"],
                ],
            },
            "recommended": True,
        },
        {
            "id": "backup_play_state",
            "effect": "snapshots every detected Play-owned skill, hook, launcher, profile, portable copy, model asset, and plugin state before convergence; restores it automatically if verification fails",
            "targets": selected,
            "recommended": True,
        },
        {
            "id": "retain_play_backups",
            "effect": f"retains the newest {BACKUP_RETENTION} verified recovery points and prints a dossier restore command when prior Play state exists",
            "existing_recovery_points": len(recovery_catalog["backups"]),
            "recommended": True,
        },
        {
            "id": "install_play",
            "effect": install_effects[play_install_state],
            "targets": selected,
        },
        {
            "id": "install_hooks",
            "effect": "installs exactly one Play-owned hook set in each harness's user configuration; marketplace bundles declare no competing hooks",
            "native_plugin_targets": [],
            "portable_targets": portable_hook_targets,
            "targets": portable_hook_targets,
        },
        {
            "id": "verify_and_report",
            "effect": "runs preflight checks, automatically rolls back an unverified replacement, and writes JSON and Markdown receipts",
        },
    ]
    play_version = str(play_state["target_version"])
    body = {
        "schema": PLAN_SCHEMA,
        "play_version": play_version,
        "play": play_state,
        "os": _os_snapshot(),
        "top_k": top_k,
        "default_selected_harnesses": DEFAULT_SELECTED_HARNESSES,
        "max_parallel_harnesses": MAX_PARALLEL_HARNESSES,
        "selected_harnesses": selected,
        "shared_agents": shared_agents,
        "recovery": {
            "retention": BACKUP_RETENTION,
            "existing_recovery_points": len(recovery_catalog["backups"]),
            "latest_backup_run_id": (
                recovery_catalog["backups"][0]["run_id"]
                if recovery_catalog["backups"]
                else None
            ),
        },
        "targets": [asdict(target) for target in targets],
        "rote": rote_state,
        "rote_skills": rote_skills,
        "tulving": tulving,
        "actions": actions,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {**body, "plan_id": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def install_journey_model_assets(source: Path, *, home: Path | None = None) -> Step:
    """Seed the owner model config once and refresh the derived price cache."""

    owner_root = (
        home.expanduser()
        if home is not None
        else Path(os.environ.get("PLAY_HOME", _home() / ".play")).expanduser()
    )
    bundled = source / "references" / "journey"
    source_config = bundled / "model-config.yaml"
    source_catalog = bundled / "model_prices_and_context_window.json"
    if not source_config.is_file() or not source_catalog.is_file():
        raise BootstrapError("bundled Journey model telemetry assets are missing")
    try:
        catalog = json.loads(source_catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"bundled LiteLLM catalog is invalid: {error}") from error
    if not isinstance(catalog, dict) or "gpt-5" not in catalog:
        raise BootstrapError("bundled LiteLLM catalog is incomplete")

    owner_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner_root.chmod(0o700)
    config_target = owner_root / "model-config.yaml"
    cache_target = owner_root / "cache" / source_catalog.name
    cache_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_target.parent.chmod(0o700)

    def copy_atomic(source_path: Path, target: Path) -> None:
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            shutil.copyfile(source_path, temporary)
            temporary.chmod(0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    created = not config_target.exists()
    if created:
        copy_atomic(source_config, config_target)
    catalog_changed = (
        not cache_target.is_file()
        or cache_target.stat().st_size != source_catalog.stat().st_size
        or hashlib.sha256(cache_target.read_bytes()).digest()
        != hashlib.sha256(source_catalog.read_bytes()).digest()
    )
    if catalog_changed:
        copy_atomic(source_catalog, cache_target)
    changed = created or catalog_changed
    if created:
        detail = f"Created {config_target} and refreshed {cache_target}"
    elif catalog_changed:
        detail = f"Preserved {config_target} and refreshed {cache_target}"
    else:
        detail = f"Preserved {config_target}; model catalog is already current"
    return Step(
        "install_journey_model_assets",
        "completed" if changed else "unchanged",
        detail,
        changed=changed,
        evidence=str(config_target),
    )


def _activation_profile_state_path() -> Path:
    override = os.environ.get("PLAY_PROFILE_STATE")
    if override:
        return Path(override).expanduser().resolve()
    state_home = Path(
        os.environ.get("XDG_STATE_HOME", _home() / ".local" / "state")
    ).expanduser()
    return state_home / "play-skill" / "activation-profile.json"


def _portable_play_path() -> Path:
    override = os.environ.get("PLAY_INSTALL_HOME")
    if override:
        return Path(override).expanduser().resolve() / "skill"
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", _home() / ".local" / "share")
    ).expanduser()
    return data_home / "modiqo" / "play" / "skill"


def _derived_play_cache_paths() -> tuple[Path, Path]:
    """Return the replaceable catalog and prompt-index cache paths."""

    state_home = Path(
        os.environ.get("PLAY_STATE_HOME", _home() / ".rote-play")
    ).expanduser()
    inbox_cache = Path(
        os.environ.get("PLAY_INBOX_CACHE_PATH", state_home / "inbox-cache.json")
    ).expanduser()
    intercept_index = Path(
        os.environ.get(
            "PLAY_INTERCEPT_INDEX_PATH", state_home / "intercept-index.json"
        )
    ).expanduser()
    return inbox_cache, intercept_index


def _play_state_candidates(
    selected: Sequence[str], plan_targets: dict[str, dict[str, Any]]
) -> list[Path]:
    """Enumerate Play-owned harness state before an overwrite begins."""

    home = _home()
    play_home = Path(os.environ.get("PLAY_HOME", home / ".play")).expanduser()
    state_path = _activation_profile_state_path()
    candidates = [
        state_path,
        state_path.parent / "profile-backups",
        _portable_play_path(),
        Path(
            os.environ.get(
                "PLAY_MACHINE_LAUNCHER", home / ".local" / "bin" / "play-machine"
            )
        ).expanduser(),
        Path(
            os.environ.get(
                "PLAY_ROUTING_LAUNCHER", home / ".local" / "bin" / "play-routing"
            )
        ).expanduser(),
        Path(
            os.environ.get(
                "PLAY_JOURNEY_LAUNCHER", home / ".local" / "bin" / "play-journey"
            )
        ).expanduser(),
        Path(
            os.environ.get("PLAY_CLI_LAUNCHER", home / ".local" / "bin" / "play")
        ).expanduser(),
        play_home / "model-config.yaml",
        play_home / "cache" / "model_prices_and_context_window.json",
        *_derived_play_cache_paths(),
    ]
    hooks = _hook_paths()
    for harness in selected:
        target = plan_targets.get(harness, {})
        roots = target.get("skill_roots", []) if isinstance(target, dict) else []
        if isinstance(roots, list):
            candidates.extend(Path(str(root)).expanduser() / "play" for root in roots)
        hook = hooks.get(harness)
        if hook is not None:
            candidates.append(hook)
            if hook.parent.is_dir():
                candidates.extend(hook.parent.glob(f"{hook.name}*play*"))

    if "codex" in selected:
        codex = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
        candidates.extend(
            [
                codex / "config.toml",
                codex / "plugins" / "cache" / PLAY_MARKETPLACE,
                codex / ".tmp" / "marketplaces" / PLAY_MARKETPLACE,
            ]
        )
    if "claude" in selected:
        claude = Path(
            os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")
        ).expanduser()
        candidates.extend(
            [
                claude / "plugins" / "cache" / PLAY_MARKETPLACE,
                claude / "plugins" / "marketplaces" / PLAY_MARKETPLACE,
                claude / "plugins" / "data" / "play-play-skills",
                claude / "plugins" / "installed_plugins.json",
                claude / "plugins" / "known_marketplaces.json",
            ]
        )
    if "opencode" in selected:
        opencode = Path(
            os.environ.get("OPENCODE_CONFIG_DIR", home / ".config" / "opencode")
        ).expanduser()
        candidates.append(opencode / "commands" / "play.md")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        absolute = candidate.absolute()
        key = str(absolute)
        if key not in seen:
            seen.add(key)
            unique.append(absolute)
    return unique


def _backup_state_paths(
    paths: Sequence[Path],
    selected: Sequence[str],
    *,
    run_id: str,
    purpose: str,
    source_backup_run_id: str | None = None,
) -> Path:
    """Snapshot exact path presence so a later restore can also remove additions."""

    root = _backup_root() / run_id
    if root.exists() or root.is_symlink():
        raise BootstrapError(f"refusing to replace existing Play backup: {root}")
    entries_root = root / "entries"
    entries_root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    entries: list[dict[str, Any]] = []
    try:
        for index, source in enumerate(paths):
            source = source.absolute()
            if not source.exists() and not source.is_symlink():
                entries.append(
                    {
                        "path": str(source),
                        "kind": "absent",
                        "backup": None,
                    }
                )
                continue
            relative = Path("entries") / f"{index:03d}-{source.name}"
            destination = root / relative
            if source.is_symlink():
                entries.append(
                    {
                        "path": str(source),
                        "kind": "symlink",
                        "target": os.readlink(source),
                        "backup": None,
                    }
                )
                continue
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
                kind = "directory"
            elif source.is_file():
                shutil.copy2(source, destination, follow_symlinks=False)
                kind = "file"
            else:
                raise BootstrapError(f"unsupported Play state path: {source}")
            entries.append(
                {
                    "path": str(source),
                    "kind": kind,
                    "backup": str(relative),
                }
            )
        manifest = root / "manifest.json"
        payload: dict[str, Any] = {
            "schema": BACKUP_SCHEMA,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "selected_harnesses": list(selected),
            "entries": entries,
        }
        if source_backup_run_id is not None:
            payload["source_backup_run_id"] = source_backup_run_id
        _atomic_json(manifest, payload)
        return manifest
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def backup_play_state(
    selected: Sequence[str],
    plan_targets: dict[str, dict[str, Any]],
    *,
    run_id: str,
) -> Path:
    """Create an owner-private, restorable snapshot before Play convergence."""

    return _backup_state_paths(
        _play_state_candidates(selected, plan_targets),
        selected,
        run_id=run_id,
        purpose="install",
    )


def _hook_paths() -> dict[str, Path]:
    home = _home()
    return {
        "codex": Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser() / "hooks.json",
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser() / "settings.json",
        "cursor": Path(os.environ.get("CURSOR_CONFIG_DIR", home / ".cursor")).expanduser() / "hooks.json",
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"cannot safely read hook configuration {path}: {error}") from error
    if not isinstance(value, dict):
        raise BootstrapError(f"hook configuration must contain an object: {path}")
    return value


def converge_claude_tulving_mcp(
    claude_executable: str,
    tulving_executable: str,
    *,
    runner: Runner = run,
) -> Step:
    """Point Claude's user-scoped Tulving MCP server at the resolved binary."""

    inspect_command = [claude_executable, "mcp", "get", "tulving"]
    inspected = runner(inspect_command)
    current = inspected.stdout if inspected.returncode == 0 else ""
    expected_command = f"  Command: {tulving_executable}"
    if (
        expected_command in current.splitlines()
        and "  Args: mcp" in current.splitlines()
    ):
        return Step(
            "configure_tulving_mcp",
            "unchanged",
            f"Claude Code already uses {tulving_executable} for Tulving recall.",
            command=inspect_command,
            target="claude",
            evidence=tulving_executable,
        )

    if inspected.returncode == 0:
        remove_command = [
            claude_executable,
            "mcp",
            "remove",
            "tulving",
            "--scope",
            "user",
        ]
        removed = runner(remove_command)
        if removed.returncode != 0:
            return Step(
                "configure_tulving_mcp",
                "review_required",
                "Claude Code could not remove its stale Tulving MCP registration: "
                + (
                    removed.stderr
                    or removed.stdout
                    or f"exit {removed.returncode}"
                ).strip(),
                command=remove_command,
                target="claude",
            )

    add_command = [
        claude_executable,
        "mcp",
        "add",
        "tulving",
        "--scope",
        "user",
        "--",
        tulving_executable,
        "mcp",
    ]
    added = runner(add_command)
    if added.returncode != 0:
        return Step(
            "configure_tulving_mcp",
            "review_required",
            "Claude Code could not register the resolved Tulving binary: "
            + (added.stderr or added.stdout or f"exit {added.returncode}").strip(),
            command=add_command,
            target="claude",
            changed=inspected.returncode == 0,
        )
    return Step(
        "configure_tulving_mcp",
        "completed",
        f"Mapped Claude Code's Tulving MCP server to {tulving_executable}.",
        command=add_command,
        target="claude",
        changed=True,
        evidence=tulving_executable,
    )


def _command_json(
    result: subprocess.CompletedProcess[str], command: Sequence[str]
) -> Any:
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise BootstrapError(
            f"command failed ({shlex.join(command)}): {output or f'exit {result.returncode}'}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BootstrapError(
            f"command returned invalid JSON ({shlex.join(command)}): {error}"
        ) from error


def _marketplace_names(harness: str, value: Any) -> set[str]:
    if harness == "codex":
        if not isinstance(value, dict) or not isinstance(value.get("marketplaces"), list):
            raise BootstrapError("Codex marketplace list returned an unexpected shape")
        records = value["marketplaces"]
    elif harness == "claude":
        if not isinstance(value, list):
            raise BootstrapError("Claude marketplace list returned an unexpected shape")
        records = value
    else:
        raise BootstrapError(f"Play marketplace convergence is unsupported for {harness}")
    return {
        str(record.get("name"))
        for record in records
        if isinstance(record, dict) and isinstance(record.get("name"), str)
    }


def _play_plugin_record(
    harness: str, value: Any, *, scope: str | None = None
) -> dict[str, Any] | None:
    if harness == "codex":
        if not isinstance(value, dict) or not isinstance(value.get("installed"), list):
            raise BootstrapError("Codex plugin list returned an unexpected shape")
        records = value["installed"]
        key = "pluginId"
    elif harness == "claude":
        if not isinstance(value, list):
            raise BootstrapError("Claude plugin list returned an unexpected shape")
        records = value
        key = "id"
    else:
        raise BootstrapError(f"Play marketplace convergence is unsupported for {harness}")
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get(key) == PLAY_PLUGIN
    ]
    if harness == "claude" and scope is not None:
        return next((record for record in matches if record.get("scope") == scope), None)
    return matches[0] if matches else None


def _marketplace_list_command(harness: str, executable: str) -> list[str]:
    return [executable, "plugin", "marketplace", "list", "--json"]


def _marketplace_is_local(harness: str, payload: object, name: str) -> bool:
    records = payload.get("marketplaces") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return False
    for record in records:
        if not isinstance(record, dict) or record.get("name") != name:
            continue
        if harness == "codex":
            source = record.get("marketplaceSource")
            return isinstance(source, dict) and source.get("sourceType") == "local"
        source = record.get("source")
        return source in {"directory", "local"}
    return False


def _plugin_list_command(harness: str, executable: str) -> list[str]:
    if harness == "codex":
        return [
            executable,
            "plugin",
            "list",
            "--marketplace",
            PLAY_MARKETPLACE,
            "--json",
            "--available",
        ]
    return [executable, "plugin", "list", "--json"]


_PLUGIN_RUNTIME_FILES = {".DS_Store", ".in_use"}


def _plugin_payload_fingerprint(root: Path) -> str | None:
    """Hash an installed plugin without harness-owned runtime markers."""

    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    try:
        entries = [
            child
            for child in root.rglob("*")
            if child.name not in _PLUGIN_RUNTIME_FILES
            and "__pycache__" not in child.parts
            and child.suffix != ".pyc"
            and (child.is_file() or child.is_symlink())
        ]
        for child in sorted(entries, key=lambda item: str(item.relative_to(root))):
            relative = str(child.relative_to(root)).encode()
            digest.update(relative + b"\0")
            if child.is_symlink():
                digest.update(b"symlink\0" + os.readlink(child).encode())
            else:
                digest.update(b"file\0" + child.read_bytes())
    except OSError:
        return None
    return digest.hexdigest()


def _installed_plugin_root(harness: str, record: dict[str, Any]) -> Path | None:
    if harness == "claude":
        value = record.get("installPath")
    else:
        source = record.get("source")
        value = source.get("path") if isinstance(source, dict) else None
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser()


def _plugin_skill_root(root: Path | None) -> Path | None:
    if root is None:
        return None
    packaged = root / "skills" / "play"
    return packaged if packaged.is_dir() else root


def converge_play_marketplace(
    harness: str,
    executable: str,
    *,
    expected_version: str,
    expected_plugin_root: Path | None = None,
    runner: Runner,
) -> list[Step]:
    """Converge the harness-native plugin, replacing it only when content differs."""

    steps: list[Step] = []
    marketplace_list = _marketplace_list_command(harness, executable)
    marketplace_result = runner(marketplace_list)
    try:
        marketplace_payload = _command_json(marketplace_result, marketplace_list)
        marketplaces = _marketplace_names(
            harness, marketplace_payload
        )
    except BootstrapError as error:
        return [
            Step(
                "inspect_play_marketplace",
                "failed",
                str(error),
                command=marketplace_list,
                target=harness,
            )
        ]
    steps.append(
        Step(
            "inspect_play_marketplace",
            "completed",
            f"Inspected configured {harness} marketplaces.",
            command=marketplace_list,
            target=harness,
        )
    )

    plugin_list = _plugin_list_command(harness, executable)
    scope = "user"
    existing: dict[str, Any] | None = None
    if PLAY_MARKETPLACE in marketplaces:
        plugin_result = runner(plugin_list)
        try:
            existing = _play_plugin_record(
                harness,
                _command_json(plugin_result, plugin_list),
                scope=scope if harness == "claude" else None,
            )
        except BootstrapError as error:
            steps.append(
                Step(
                    "inspect_play_plugin",
                    "failed",
                    str(error),
                    command=plugin_list,
                    target=harness,
                )
            )
            return steps
        steps.append(
            Step(
                "inspect_play_plugin",
                "completed",
                (
                    f"Found Play {existing.get('version', 'unknown')} before convergence."
                    if existing
                    else "Play was not installed before convergence."
                ),
                command=plugin_list,
                target=harness,
            )
        )
        installed_root = _installed_plugin_root(harness, existing) if existing else None
        expected_skill_root = _plugin_skill_root(expected_plugin_root)
        installed_skill_root = _plugin_skill_root(installed_root)
        expected_fingerprint = (
            _plugin_payload_fingerprint(expected_skill_root)
            if expected_skill_root is not None
            else None
        )
        installed_fingerprint = (
            _plugin_payload_fingerprint(installed_skill_root)
            if installed_skill_root is not None
            else None
        )
        plugin_errors = existing.get("errors") if existing else None
        current = (
            existing is not None
            and existing.get("version") == expected_version
            and existing.get("enabled") is not False
            and not plugin_errors
            and expected_fingerprint is not None
            and installed_fingerprint == expected_fingerprint
        )
        if current:
            steps.append(
                Step(
                    "verify_play_plugin",
                    "unchanged",
                    f"Play {expected_version} is installed, enabled, healthy, and byte-current.",
                    command=plugin_list,
                    target=harness,
                    changed=False,
                    evidence=json.dumps(existing, sort_keys=True),
                )
            )
            return steps

    local_marketplace = (
        PLAY_MARKETPLACE in marketplaces
        and _marketplace_is_local(harness, marketplace_payload, PLAY_MARKETPLACE)
    )
    refresh_command: list[str] | None = None
    refresh_id = "refresh_play_marketplace"
    if local_marketplace:
        steps.append(
            Step(
                "refresh_play_marketplace",
                "unchanged",
                f"Local {harness} marketplace reads directly from its configured directory.",
                target=harness,
                changed=False,
            )
        )
    elif PLAY_MARKETPLACE in marketplaces:
        refresh_command = [
            executable,
            "plugin",
            "marketplace",
            "upgrade" if harness == "codex" else "update",
            PLAY_MARKETPLACE,
        ]
        refresh_id = "refresh_play_marketplace"
    else:
        refresh_command = [
            executable,
            "plugin",
            "marketplace",
            "add",
            PLAY_REPOSITORY,
        ]
        refresh_id = "add_play_marketplace"
    if not local_marketplace:
        assert refresh_command is not None
        refresh_result = runner(refresh_command)
        steps.append(
            _result_step(refresh_id, refresh_result, refresh_command, target=harness)
        )
        if refresh_result.returncode != 0:
            return steps

    if PLAY_MARKETPLACE not in marketplaces:
        plugin_result = runner(plugin_list)
        try:
            existing = _play_plugin_record(
                harness,
                _command_json(plugin_result, plugin_list),
                scope=scope if harness == "claude" else None,
            )
        except BootstrapError as error:
            steps.append(
                Step(
                    "inspect_play_plugin",
                    "failed",
                    str(error),
                    command=plugin_list,
                    target=harness,
                )
            )
            return steps
        steps.append(
            Step(
                "inspect_play_plugin",
                "completed",
                "Play was not installed before convergence." if existing is None else (
                    f"Found Play {existing.get('version', 'unknown')} before convergence."
                ),
                command=plugin_list,
                target=harness,
            )
        )

    if existing is not None:
        if harness == "codex":
            remove_command = [executable, "plugin", "remove", PLAY_PLUGIN]
        else:
            remove_command = [
                executable,
                "plugin",
                "uninstall",
                PLAY_PLUGIN,
                "--scope",
                scope,
            ]
        remove_result = runner(remove_command)
        steps.append(
            _result_step(
                "remove_stale_play_plugin",
                remove_result,
                remove_command,
                target=harness,
            )
        )
        if remove_result.returncode != 0:
            return steps
    else:
        steps.append(
            Step(
                "remove_stale_play_plugin",
                "unchanged",
                "No installed Play plugin needed removal.",
                target=harness,
            )
        )

    if harness == "codex":
        install_command = [executable, "plugin", "add", PLAY_PLUGIN]
    else:
        install_command = [
            executable,
            "plugin",
            "install",
            PLAY_PLUGIN,
            "--scope",
            scope,
        ]
    install_result = runner(install_command)
    steps.append(
        _result_step(
            "install_current_play_plugin",
            install_result,
            install_command,
            target=harness,
        )
    )
    if install_result.returncode != 0:
        return steps

    verify_result = runner(plugin_list)
    try:
        installed = _play_plugin_record(
            harness,
            _command_json(verify_result, plugin_list),
            scope=scope if harness == "claude" else None,
        )
    except BootstrapError as error:
        steps.append(
            Step(
                "verify_play_plugin",
                "failed",
                str(error),
                command=plugin_list,
                target=harness,
            )
        )
        return steps
    installed_version = installed.get("version") if installed else None
    enabled = installed.get("enabled") if installed else None
    plugin_errors = installed.get("errors") if installed else None
    healthy = not plugin_errors
    verified = installed_version == expected_version and enabled is not False and healthy
    steps.append(
        Step(
            "verify_play_plugin",
            "completed" if verified else "failed",
            (
                f"Play {installed_version} is installed, enabled, and healthy."
                if verified
                else (
                    f"Expected Play {expected_version} enabled after reinstall; "
                    f"found version={installed_version!r}, enabled={enabled!r}, "
                    f"errors={plugin_errors!r}."
                )
            ),
            command=plugin_list,
            target=harness,
            evidence=json.dumps(installed, sort_keys=True) if installed else None,
        )
    )
    return steps


def _is_play_skill_config(entry: dict[str, Any]) -> bool:
    if entry.get("name") == "play":
        return True
    path = entry.get("path")
    if not isinstance(path, str):
        return False
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.endswith("/skills/play/SKILL.md") or normalized.endswith(
        "/skills/play"
    )


def _fallback_skill_config_entries(text: str) -> list[dict[str, Any]]:
    """Read the small [[skills.config]] surface on Python 3.10 without tomllib."""

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "[[skills.config]]":
            current = {}
            entries.append(current)
            continue
        if line.startswith("["):
            current = None
            continue
        if current is None or not line or line.startswith("#"):
            continue
        match = re.match(r"^(name|path|enabled)\s*=\s*(.+?)\s*$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        if key == "enabled":
            if raw_value in {"true", "false"}:
                current[key] = raw_value == "true"
            continue
        if (
            len(raw_value) >= 2
            and raw_value[0] == raw_value[-1]
            and raw_value[0] in {'"', "'"}
        ):
            current[key] = raw_value[1:-1]
    return entries


def _codex_skill_config_entries(text: str, path: Path) -> list[dict[str, Any]]:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 bootstrap path.
        return _fallback_skill_config_entries(text)
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise BootstrapError(f"cannot safely read Codex configuration {path}: {error}") from error
    skills = value.get("skills")
    if not isinstance(skills, dict):
        return []
    entries = skills.get("config", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise BootstrapError(f"Codex skills.config must be a list in {path}")
    return [entry for entry in entries if isinstance(entry, dict)]


def codex_disabled_play_entries() -> list[str]:
    codex_home = Path(os.environ.get("CODEX_HOME", _home() / ".codex")).expanduser()
    path = codex_home / "config.toml"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise BootstrapError(f"cannot safely read Codex configuration {path}: {error}") from error
    entries = _codex_skill_config_entries(text, path)
    return [
        str(entry.get("path") or entry.get("name") or "play")
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("enabled") is False
        and _is_play_skill_config(entry)
    ]


def _strip_codex_play_skill_blocks(text: str) -> tuple[str, int]:
    """Remove explicit Play skill overrides while preserving unrelated TOML."""

    header = re.compile(r"(?m)^\[\[skills\.config\]\]\s*(?:\r?\n|$)")
    matches = list(header.finditer(text))
    table_headers = list(re.finditer(r"(?m)^\[", text))
    if not matches:
        return text, 0
    pieces: list[str] = []
    cursor = 0
    removed = 0
    for match in matches:
        start = match.start()
        end = next(
            (candidate.start() for candidate in table_headers if candidate.start() > start),
            len(text),
        )
        block = text[start:end]
        entries = _fallback_skill_config_entries(block)
        if len(entries) == 1 and _is_play_skill_config(entries[0]):
            pieces.append(text[cursor:start])
            cursor = end
            removed += 1
    pieces.append(text[cursor:])
    updated = "".join(pieces)
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    return updated, removed


def codex_play_enablement_step() -> Step:
    codex_home = Path(os.environ.get("CODEX_HOME", _home() / ".codex")).expanduser()
    path = codex_home / "config.toml"
    if not path.is_file():
        return Step(
            "enable_play_skill",
            "unchanged",
            "No explicit Codex Play skill override was found.",
            target="codex",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise BootstrapError(f"cannot safely read Codex configuration {path}: {error}") from error
    # Parse first so malformed TOML still fails closed before an overwrite.
    _codex_skill_config_entries(text, path)
    updated, removed = _strip_codex_play_skill_blocks(text)
    if removed:
        mode = path.stat().st_mode & 0o777
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(updated, encoding="utf-8")
            temporary.chmod(mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return Step(
            "enable_play_skill",
            "completed",
            f"Removed {removed} explicit Codex Play skill override(s); the reinstalled plugin now owns enablement.",
            target="codex",
            changed=True,
            evidence=str(path),
        )
    return Step(
        "enable_play_skill",
        "unchanged",
        "No explicit disabled Play skill override was found in Codex.",
        target="codex",
    )


def _is_play_hook(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    if isinstance(command, str) and ("play-intercept" in command or "play-inbox" in command):
        return True
    hooks = value.get("hooks")
    return isinstance(hooks, list) and any(_is_play_hook(item) for item in hooks)


def _nested_hook(command: str, *, matcher: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hooks": [{"type": "command", "command": command, "timeout": 5}]
    }
    if matcher:
        value["matcher"] = matcher
    return value


def _codex_hook_event_name(event: str) -> str:
    """Return the snake-case event name Codex uses in hooks.state keys."""

    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def _codex_play_hook_state_keys(
    value: dict[str, Any], hook_path: Path
) -> set[str]:
    """Resolve only the Codex state keys owned by Play hook commands."""

    keys = {
        f"{PLAY_PLUGIN}:hooks/hooks.json:session_start:0:0",
        f"{PLAY_PLUGIN}:hooks/hooks.json:user_prompt_submit:0:0",
        f"{PLAY_PLUGIN}:hooks/hooks.json:stop:0:0",
    }
    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        return keys
    for event, entries in hooks.items():
        if not isinstance(event, str) or not isinstance(entries, list):
            continue
        for entry_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            handlers = entry.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler_index, handler in enumerate(handlers):
                if _is_play_hook(handler):
                    keys.add(
                        f"{hook_path}:{_codex_hook_event_name(event)}:"
                        f"{entry_index}:{handler_index}"
                    )
    return keys


def _enable_codex_play_hook_state(
    value: dict[str, Any], hook_path: Path
) -> int:
    """Clear Play-only disabled flags while preserving all unrelated Codex state."""

    codex_home = Path(
        os.environ.get("CODEX_HOME", _home() / ".codex")
    ).expanduser()
    config_path = codex_home / "config.toml"
    if not config_path.is_file():
        return 0
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise BootstrapError(
            f"cannot safely read Codex configuration {config_path}: {error}"
        ) from error
    # Reuse the bootstrap's Python 3.10-compatible TOML validation path before
    # preserving the document's formatting with a targeted textual update.
    _codex_skill_config_entries(text, config_path)

    owned_keys = _codex_play_hook_state_keys(value, hook_path)
    header = re.compile(r'(?m)^\[hooks\.state\."([^"]+)"\]\s*(?:\r?\n|$)')
    matches = list(header.finditer(text))
    table_headers = list(re.finditer(r"(?m)^\[", text))
    updated = text
    replacements: list[tuple[int, int, str]] = []
    enabled_count = 0
    for match in matches:
        if match.group(1) not in owned_keys:
            continue
        start = match.start()
        end = next(
            (candidate.start() for candidate in table_headers if candidate.start() > start),
            len(text),
        )
        block = text[start:end]
        enabled_block, count = re.subn(
            r"(?m)^enabled\s*=\s*false\s*$", "enabled = true", block
        )
        if count:
            replacements.append((start, end, enabled_block))
            enabled_count += count
    for start, end, replacement in reversed(replacements):
        updated = updated[:start] + replacement + updated[end:]
    if not enabled_count:
        return 0
    mode = config_path.stat().st_mode & 0o777
    temporary = config_path.with_name(f".{config_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(updated, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, config_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return enabled_count


def _verify_prompt_intercept(source: Path, *, verify_catalog: bool = False) -> None:
    """Execute deterministic activation and cached-catalog probes after replacement."""

    command = source / "scripts" / "bin" / "play-intercept"
    try:
        result = subprocess.run(
            [str(command), "prompt"],
            input=json.dumps({"prompt": "play cheat-sheet"}),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BootstrapError(f"Play prompt hook smoke check failed: {error}") from error
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BootstrapError(
            "Play prompt hook smoke check returned invalid output: "
            f"{(result.stderr or result.stdout).strip() or f'exit {result.returncode}'}"
        ) from error
    context = payload.get("hookSpecificOutput", {}).get("additionalContext")
    if result.returncode != 0 or not isinstance(context, str) or "cheat-sheet" not in context:
        raise BootstrapError(
            "Play prompt hook smoke check did not emit activation context: "
            f"{(result.stderr or result.stdout).strip() or f'exit {result.returncode}'}"
        )
    if not verify_catalog:
        return
    cache_path = Path(
        os.environ.get(
            "PLAY_INBOX_CACHE_PATH", _home() / ".rote-play" / "inbox-cache.json"
        )
    ).expanduser()
    # Unit/dry runners can return a synthetic warm-cache receipt without
    # creating host state. A real installer run writes this file before hook
    # convergence; whenever it exists, the catalog probe below is mandatory.
    if not cache_path.is_file():
        return
    cache = _load_json(cache_path)
    catalog = cache.get("catalog")
    public_catalog = cache.get("public_catalog")
    if cache.get("catalog_complete") is not True or not (
        isinstance(catalog, list) or isinstance(public_catalog, list)
    ):
        raise BootstrapError(
            "Play prompt hook catalog smoke check requires a verified complete inbox cache"
        )
    safe_catalog = public_cache_entries(cache)
    candidate = next(
        (
            item
            for item in safe_catalog
            if isinstance(item, dict)
            and isinstance(item.get("reference"), str)
            and isinstance(item.get("name"), str)
            and len(re.findall(r"[a-z0-9]+", item["name"].casefold())) >= 2
        ),
        None,
    )
    if candidate is None:
        return
    prompt = "find " + str(candidate["name"]).replace("-", " ").replace("_", " ")
    cached_result = subprocess.run(
        [str(command), "prompt"],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    try:
        cached_payload = json.loads(cached_result.stdout)
    except json.JSONDecodeError as error:
        raise BootstrapError(
            "Play prompt hook cached-catalog smoke check returned invalid output: "
            f"{(cached_result.stderr or cached_result.stdout).strip() or f'exit {cached_result.returncode}'}"
        ) from error
    cached_context = cached_payload.get("hookSpecificOutput", {}).get(
        "additionalContext"
    )
    if (
        cached_result.returncode != 0
        or not isinstance(cached_context, str)
        or str(candidate["reference"]) not in cached_context
    ):
        raise BootstrapError(
            "Play prompt hook did not resolve the verified cached catalog entry: "
            f"{candidate['reference']}"
        )


def _managed_hook_entries(harness: str, source: Path) -> dict[str, list[dict[str, Any]]]:
    intercept = shlex.quote(str(source / "scripts" / "bin" / "play-intercept"))
    inbox = shlex.quote(str(source / "scripts" / "bin" / "play-inbox"))
    prompt = f"{intercept} prompt 2>/dev/null || true"
    stop = f"{intercept} milestone-nudge 2>/dev/null || true"
    session = f"{inbox} line 2>/dev/null; ({inbox} refresh --if-older-than 6 >/dev/null 2>&1 &)"
    if harness in {"codex", "claude"}:
        return {
            "UserPromptSubmit": [_nested_hook(prompt)],
            "Stop": [_nested_hook(stop)],
            "SessionStart": [_nested_hook(session, matcher="startup|resume")],
        }
    if harness == "cursor":
        return {
            "beforeSubmitPrompt": [{"command": prompt, "timeout": 5}],
            "stop": [{"command": stop, "timeout": 5}],
            "sessionStart": [{"command": session, "timeout": 5}],
        }
    raise BootstrapError(f"hooks are unsupported for {harness}")


def install_hooks(
    harness: str, source: Path, *, run_id: str, verify_catalog: bool = False
) -> Step:
    path = _hook_paths().get(harness)
    if path is None:
        return Step("install_hooks", "unsupported", "No verified native hook surface.", target=harness)
    value = _load_json(path)
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BootstrapError(f"hooks must be an object in {path}")
    desired = _managed_hook_entries(harness, source)
    for event, entries in desired.items():
        current = hooks.get(event, [])
        if not isinstance(current, list):
            raise BootstrapError(f"hook event {event} must be a list in {path}")
        preserved = [entry for entry in current if not _is_play_hook(entry)]
        # An approved install is a convergence boundary: remove every prior
        # Play-owned entry and append a fresh canonical copy even when the
        # serialized command happens to be unchanged.
        hooks[event] = [*preserved, *entries]
    if harness == "cursor":
        value["version"] = 1
    backup: Path | None = None
    if path.exists():
        backup = path.with_name(f"{path.name}.play-backup-{run_id}")
        if backup.exists():
            raise BootstrapError(f"refusing to replace existing hook backup: {backup}")
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    _atomic_json(path, value)
    enabled_count = (
        _enable_codex_play_hook_state(value, path) if harness == "codex" else 0
    )
    _verify_prompt_intercept(source, verify_catalog=verify_catalog)
    state_detail = (
        f" Reset {enabled_count} disabled Play-only Codex hook state entr"
        f"{'y' if enabled_count == 1 else 'ies'}."
        if enabled_count
        else ""
    )
    return Step(
        "install_hooks",
        "completed",
        f"Backed up and replaced Play prompt, stop, and session hooks in {path}; "
        f"the prompt hook smoke check passed.{state_detail}",
        target=harness,
        changed=True,
        evidence=str(backup) if backup else str(path),
    )


def remove_portable_play_hooks(harness: str, *, run_id: str) -> Step:
    """Remove legacy user hooks when a native marketplace plugin owns Play.

    Codex and Claude load hooks declared by the installed Play plugin. Older
    bootstrap releases also wrote the same hooks into user configuration,
    causing every prompt to be intercepted twice. Preserve every unrelated
    hook and converge Play to exactly one native owner.
    """

    if harness not in {"codex", "claude"}:
        raise BootstrapError(
            f"portable Play hook removal is unsupported for {harness}"
        )
    path = _hook_paths()[harness]
    if not path.exists():
        if harness == "codex":
            _enable_codex_play_hook_state({}, path)
        return Step(
            "remove_duplicate_play_hooks",
            "unchanged",
            f"{LABELS[harness]} has no user hook configuration; the Play plugin is the sole hook owner.",
            target=harness,
        )
    value = _load_json(path)
    hooks = value.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise BootstrapError(f"hooks must be an object in {path}")
    removed = 0
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            raise BootstrapError(f"hook event {event} must be a list in {path}")
        preserved = [entry for entry in entries if not _is_play_hook(entry)]
        removed += len(entries) - len(preserved)
        if preserved:
            hooks[event] = preserved
        else:
            hooks.pop(event)
    enabled_count = (
        _enable_codex_play_hook_state(value, path) if harness == "codex" else 0
    )
    if not removed:
        return Step(
            "remove_duplicate_play_hooks",
            "unchanged",
            f"No portable Play hooks remain in {path}; the Play plugin is the sole hook owner.",
            target=harness,
        )
    backup = path.with_name(f"{path.name}.play-backup-{run_id}")
    if backup.exists():
        raise BootstrapError(f"refusing to replace existing hook backup: {backup}")
    backup.write_bytes(path.read_bytes())
    backup.chmod(0o600)
    value["hooks"] = hooks
    _atomic_json(path, value)
    suffix = (
        f" Reset {enabled_count} disabled Play plugin hook state entr"
        f"{'y' if enabled_count == 1 else 'ies'}."
        if enabled_count
        else ""
    )
    return Step(
        "remove_duplicate_play_hooks",
        "completed",
        f"Removed {removed} legacy Play hook entr"
        f"{'y' if removed == 1 else 'ies'} from {path}; the marketplace plugin is now the sole hook owner.{suffix}",
        target=harness,
        changed=True,
        evidence=str(backup),
    )


def _result_step(
    step_id: str,
    result: subprocess.CompletedProcess[str],
    command: Sequence[str],
    *,
    target: str | None = None,
) -> Step:
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0 and stdout and stderr:
        output = f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
    else:
        output = stdout or stderr
    return Step(
        step_id,
        "completed" if result.returncode == 0 else "failed",
        output or f"exit {result.returncode}",
        command=list(command),
        target=target,
        changed=result.returncode == 0,
    )


def _warm_public_play_cache(
    source: Path,
    *,
    runner: Runner,
    progress: Progress,
) -> Step:
    """Best-effort warm and validation of the first bounded Play snapshot."""

    command = [
        sys.executable,
        str(source / "scripts" / "bin" / "play-inbox"),
        "refresh",
        "--days",
        "7",
        "--require-complete-catalog",
        "--json",
    ]
    result = progress.command("Caching public Plays", runner, command)
    if result.returncode != 0:
        if _registry_network_failure(result):
            return Step(
                "warm_public_play_cache",
                "skipped",
                "Play discovery cache warmup was skipped; live search will be used "
                "on cache misses. "
                + _registry_network_blocker("The bounded Play catalog refresh"),
                command=command,
            )
        output = (result.stdout or result.stderr or f"exit {result.returncode}").strip()
        return Step(
            "warm_public_play_cache",
            "skipped",
            f"Play discovery cache warmup was skipped: {output}",
            command=command,
        )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        return Step(
            "warm_public_play_cache",
            "skipped",
            "Play discovery cache warmup returned invalid JSON and was skipped: "
            f"{error}",
            command=command,
        )
    counts = payload.get("counts") if isinstance(payload, dict) else None
    public_count = counts.get("public") if isinstance(counts, dict) else None
    organization_scope = payload.get("organization_scope") if isinstance(payload, dict) else None
    baseline_scope = payload.get("baseline_scope") if isinstance(payload, dict) else None
    authority = payload.get("authority_sha256") if isinstance(payload, dict) else None
    snapshot = payload.get("catalog_sha256") if isinstance(payload, dict) else None
    valid = (
        isinstance(payload, dict)
        and payload.get("schema") == "play.inbox-cache/v1"
        and payload.get("catalog_complete") is True
        and isinstance(public_count, int)
        and not isinstance(public_count, bool)
        and public_count >= 0
        and isinstance(organization_scope, list)
        and all(isinstance(slug, str) and slug for slug in organization_scope)
        and isinstance(baseline_scope, list)
        and "modiqo" in baseline_scope
        and isinstance(authority, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", authority) is not None
        and isinstance(snapshot, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot) is not None
    )
    if not valid:
        return Step(
            "warm_public_play_cache",
            "skipped",
            "Play discovery cache warmup did not return a complete, fingerprinted "
            "snapshot; live search will be used on cache misses.",
            command=command,
        )
    assert isinstance(public_count, int)
    assert isinstance(organization_scope, list)
    assert isinstance(snapshot, str)
    org_count = len(organization_scope)
    detail = (
        f"Cached {public_count} public Play{'s' if public_count != 1 else ''} across "
        f"{org_count} organization{'s' if org_count != 1 else ''}; snapshot {snapshot}."
    )
    evidence = json.dumps(
        {
            "schema": payload["schema"],
            "catalog_complete": True,
            "catalog_sha256": snapshot,
            "authority_sha256": authority,
            "baseline_scope": baseline_scope,
            "organization_scope": organization_scope,
            "public_play_count": public_count,
        },
        sort_keys=True,
    )
    return Step(
        "warm_public_play_cache",
        "completed",
        detail,
        command=command,
        changed=payload.get("refreshed") is True,
        evidence=evidence,
    )


def _prepare_derived_play_caches() -> Step:
    """Invalidate the prompt index before the target version rebuilds it."""

    inbox_cache, intercept_index = _derived_play_cache_paths()
    if (
        intercept_index.exists()
        and intercept_index.is_dir()
        and not intercept_index.is_symlink()
    ):
        raise BootstrapError(
            f"refusing to replace a directory at the Play prompt index path: {intercept_index}"
        )
    changed = intercept_index.exists() or intercept_index.is_symlink()
    if changed:
        intercept_index.unlink()
    return Step(
        "prepare_play_caches",
        "completed" if changed else "unchanged",
        (
            "Cleared the derived Play prompt index; the target version will rebuild it."
            if changed
            else "The derived Play prompt index is ready for the target version to build."
        ),
        changed=changed,
        evidence=json.dumps(
            {
                "catalog_cache": str(inbox_cache),
                "prompt_index": str(intercept_index),
            },
            sort_keys=True,
        ),
    )


def _accept_identity_only_preflight(
    result: subprocess.CompletedProcess[str],
) -> subprocess.CompletedProcess[str]:
    """Treat an unsigned identity as onboarding, not an installation failure."""

    if result.returncode == 0:
        return result
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return result
    checks = payload.get("checks") if isinstance(payload, dict) else None
    if not isinstance(checks, list):
        return result
    failed = {
        str(check.get("id"))
        for check in checks
        if isinstance(check, dict) and check.get("ok") is False
    }
    if failed != {"authenticated"}:
        return result
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=0,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _report_root() -> Path:
    override = os.environ.get("PLAY_BOOTSTRAP_STATE")
    if override:
        return Path(override).expanduser().resolve()
    state = Path(os.environ.get("XDG_STATE_HOME", _home() / ".local" / "state")).expanduser()
    return state / "play-bootstrap"


def _backup_root() -> Path:
    return _report_root() / "backups"


def _backup_manifest_path(run_id: str) -> Path:
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise BootstrapError(f"invalid Play backup id: {run_id!r}")
    return _backup_root() / run_id / "manifest.json"


def _manifest_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_backup_manifest(path: Path) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        root = _backup_root().resolve()
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise BootstrapError(
            f"Play backup manifest must be inside {_backup_root()}: {path}"
        ) from error
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"cannot read Play backup manifest {resolved}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != BACKUP_SCHEMA:
        raise BootstrapError(f"unsupported Play backup manifest: {resolved}")
    if not isinstance(value.get("run_id"), str) or not isinstance(
        value.get("selected_harnesses"), list
    ) or not isinstance(value.get("entries"), list):
        raise BootstrapError(f"malformed Play backup manifest: {resolved}")
    for entry in value["entries"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise BootstrapError(f"malformed Play backup entry in {resolved}")
        if entry.get("kind") not in {"absent", "file", "directory", "symlink"}:
            raise BootstrapError(f"unsupported Play backup entry in {resolved}")
    return {**value, "manifest_path": str(resolved)}


def list_play_backups() -> dict[str, Any]:
    """Return valid install snapshots newest-first without changing state."""

    backups: list[dict[str, Any]] = []
    root = _backup_root()
    if root.is_dir():
        for manifest_path in root.glob("*/manifest.json"):
            try:
                manifest = _load_backup_manifest(manifest_path)
            except BootstrapError:
                continue
            existing = sum(
                1 for entry in manifest["entries"] if entry.get("kind") != "absent"
            )
            backups.append(
                {
                    "run_id": manifest["run_id"],
                    "created_at": manifest.get("created_at"),
                    "purpose": manifest.get("purpose", "install"),
                    "selected_harnesses": manifest["selected_harnesses"],
                    "entry_count": len(manifest["entries"]),
                    "existing_entry_count": existing,
                    "manifest_path": manifest["manifest_path"],
                    "manifest_sha256": _manifest_sha256(manifest_path),
                }
            )
    backups.sort(
        key=lambda item: (str(item.get("created_at") or ""), str(item["run_id"])),
        reverse=True,
    )
    return {
        "schema": BACKUP_CATALOG_SCHEMA,
        "retention": BACKUP_RETENTION,
        "backups": backups,
    }


def prune_play_backups(
    *, retain: int = BACKUP_RETENTION, protect: Sequence[str] = ()
) -> list[str]:
    """Prune oldest valid snapshots only after a verified transaction."""

    if retain < 1:
        raise BootstrapError("Play backup retention must be at least 1")
    catalog = list_play_backups()
    protected = set(protect)
    candidates = [
        item for item in reversed(catalog["backups"]) if item["run_id"] not in protected
    ]
    excess = max(0, len(catalog["backups"]) - retain)
    removed: list[str] = []
    for item in candidates[:excess]:
        manifest = Path(str(item["manifest_path"]))
        directory = manifest.parent
        try:
            directory.resolve().relative_to(_backup_root().resolve())
        except ValueError as error:
            raise BootstrapError(f"refusing to prune unsafe backup path: {directory}") from error
        shutil.rmtree(directory)
        removed.append(str(item["run_id"]))
    return removed


def _backup_from_dossier(path: Path) -> tuple[Path, str | None]:
    try:
        dossier_path = path.expanduser().resolve(strict=True)
        dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"cannot read Play install dossier {path}: {error}") from error
    if not isinstance(dossier, dict) or dossier.get("schema") != REPORT_SCHEMA:
        raise BootstrapError(f"not a Play install dossier: {dossier_path}")
    backup = dossier.get("backup")
    manifest_value = backup.get("manifest_path") if isinstance(backup, dict) else None
    expected_sha = backup.get("manifest_sha256") if isinstance(backup, dict) else None
    if not isinstance(manifest_value, str):
        manifest_value = next(
            (
                step.get("evidence")
                for step in dossier.get("steps", [])
                if isinstance(step, dict)
                and step.get("id") == "backup_play_state"
                and step.get("status") == "completed"
                and isinstance(step.get("evidence"), str)
            ),
            None,
        )
    if not isinstance(manifest_value, str):
        raise BootstrapError(f"install dossier has no restorable Play backup: {dossier_path}")
    manifest_path = Path(manifest_value).expanduser().resolve()
    _load_backup_manifest(manifest_path)
    if isinstance(expected_sha, str) and _manifest_sha256(manifest_path) != expected_sha:
        raise BootstrapError(
            f"Play backup manifest changed after the dossier was written: {manifest_path}"
        )
    return manifest_path, str(dossier_path)


def build_restore_plan(
    *, dossier: Path | None = None, backup_run_id: str | None = None
) -> dict[str, Any]:
    if (dossier is None) == (backup_run_id is None):
        raise BootstrapError("restore requires exactly one of --dossier or --backup")
    if dossier is not None:
        manifest_path, dossier_path = _backup_from_dossier(dossier)
    else:
        assert backup_run_id is not None
        manifest_path = _backup_manifest_path(backup_run_id)
        dossier_path = None
    manifest = _load_backup_manifest(manifest_path)
    entries = [
        {
            "path": entry["path"],
            "action": "remove" if entry["kind"] == "absent" else "restore",
            "kind": entry["kind"],
        }
        for entry in manifest["entries"]
    ]
    body: dict[str, Any] = {
        "schema": RESTORE_PLAN_SCHEMA,
        "backup_run_id": manifest["run_id"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": _manifest_sha256(manifest_path),
        "dossier_path": dossier_path,
        "selected_harnesses": manifest["selected_harnesses"],
        "entries": entries,
        "safety": "The current Play-owned state is backed up before any restore mutation.",
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {
        **body,
        "plan_id": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
    }


def _remove_restore_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _backup_entry_source(root: Path, entry: dict[str, Any]) -> Path | None:
    backup_value = entry.get("backup")
    if not isinstance(backup_value, str):
        return None
    source = (root / backup_value).resolve(strict=True)
    try:
        source.relative_to(root.resolve())
    except ValueError as error:
        raise BootstrapError(f"unsafe backup payload path for {entry['path']}") from error
    return source


def _play_toml_blocks(text: str) -> list[str]:
    header = re.compile(r"(?m)^\[\[skills\.config\]\]\s*(?:\r?\n|$)")
    matches = list(header.finditer(text))
    table_headers = list(re.finditer(r"(?m)^\[", text))
    blocks: list[str] = []
    for match in matches:
        start = match.start()
        end = next(
            (candidate.start() for candidate in table_headers if candidate.start() > start),
            len(text),
        )
        block = text[start:end]
        entries = _fallback_skill_config_entries(block)
        if len(entries) == 1 and _is_play_skill_config(entries[0]):
            blocks.append(block.strip("\n") + "\n")
    return blocks


def _restore_codex_config(root: Path, entry: dict[str, Any], target: Path) -> None:
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    source = _backup_entry_source(root, entry)
    previous = source.read_text(encoding="utf-8") if source is not None else ""
    # Parse both sides before touching a shared host configuration.
    _codex_skill_config_entries(current, target)
    if previous:
        _codex_skill_config_entries(previous, source or target)
    merged, _ = _strip_codex_play_skill_blocks(current)
    blocks = _play_toml_blocks(previous)
    if blocks:
        if merged and not merged.endswith("\n"):
            merged += "\n"
        merged += ("\n" if merged.strip() else "") + "\n".join(blocks)
    if merged:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.restore.tmp")
        temporary.write_text(merged, encoding="utf-8")
        temporary.chmod(target.stat().st_mode & 0o777 if target.exists() else 0o600)
        os.replace(temporary, target)
    elif target.exists():
        target.unlink()


def _restore_hook_config(root: Path, entry: dict[str, Any], target: Path) -> None:
    current = _load_json(target)
    source = _backup_entry_source(root, entry)
    previous = _load_json(source) if source is not None else {}
    current_hooks = current.get("hooks", {})
    previous_hooks = previous.get("hooks", {})
    if not isinstance(current_hooks, dict) or not isinstance(previous_hooks, dict):
        raise BootstrapError(f"hooks must be objects while restoring {target}")
    merged_hooks: dict[str, Any] = {}
    for event in sorted(set(current_hooks) | set(previous_hooks)):
        current_entries = current_hooks.get(event, [])
        previous_entries = previous_hooks.get(event, [])
        if not isinstance(current_entries, list) or not isinstance(previous_entries, list):
            raise BootstrapError(f"hook event {event} must be a list in {target}")
        merged = [item for item in current_entries if not _is_play_hook(item)]
        merged.extend(item for item in previous_entries if _is_play_hook(item))
        if merged:
            merged_hooks[event] = merged
    current["hooks"] = merged_hooks
    if current or target.exists():
        _atomic_json(target, current)


def _contains_play_plugin(value: Any) -> bool:
    try:
        serialized = json.dumps(value, sort_keys=True).lower()
    except (TypeError, ValueError):
        return False
    return any(
        marker in serialized
        for marker in ("play@play-skills", '"play-skills"', "github.com/modiqo/play")
    )


def _merge_play_plugin_json(current: Any, previous: Any) -> Any:
    if isinstance(current, dict) and isinstance(previous, dict):
        merged = dict(current)
        for key in set(current) | set(previous):
            old_present = key in previous
            new_present = key in current
            if _contains_play_plugin(key):
                if old_present:
                    merged[key] = previous[key]
                else:
                    merged.pop(key, None)
            elif old_present and new_present and isinstance(current[key], (dict, list)):
                merged[key] = _merge_play_plugin_json(current[key], previous[key])
            elif old_present and not new_present and _contains_play_plugin(previous[key]):
                merged[key] = previous[key]
        return merged
    if isinstance(current, list) and isinstance(previous, list):
        return [item for item in current if not _contains_play_plugin(item)] + [
            item for item in previous if _contains_play_plugin(item)
        ]
    return previous if _contains_play_plugin(previous) else current


def _restore_plugin_registry(root: Path, entry: dict[str, Any], target: Path) -> None:
    current = _load_json(target)
    source = _backup_entry_source(root, entry)
    previous = _load_json(source) if source is not None else {}
    _atomic_json(target, _merge_play_plugin_json(current, previous))


def _shared_restore_handler(target: Path) -> str | None:
    hooks = {path.absolute() for path in _hook_paths().values()}
    if target.absolute() in hooks:
        return "hooks"
    codex = Path(os.environ.get("CODEX_HOME", _home() / ".codex")).expanduser()
    if target.absolute() == (codex / "config.toml").absolute():
        return "codex_config"
    claude = Path(
        os.environ.get("CLAUDE_CONFIG_DIR", _home() / ".claude")
    ).expanduser()
    if target.absolute() in {
        (claude / "plugins" / "installed_plugins.json").absolute(),
        (claude / "plugins" / "known_marketplaces.json").absolute(),
    }:
        return "plugin_registry"
    return None


def _restore_manifest_entries(manifest: dict[str, Any]) -> None:
    root = Path(str(manifest["manifest_path"])).parent
    for index, entry in enumerate(manifest["entries"]):
        target = Path(str(entry["path"])).expanduser()
        kind = str(entry["kind"])
        shared_handler = _shared_restore_handler(target)
        if shared_handler == "hooks":
            _restore_hook_config(root, entry, target)
            continue
        if shared_handler == "codex_config":
            _restore_codex_config(root, entry, target)
            continue
        if shared_handler == "plugin_registry":
            _restore_plugin_registry(root, entry, target)
            continue
        if kind == "absent":
            _remove_restore_target(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f".{target.name}.play-restore-{os.getpid()}-{index}")
        if staged.exists() or staged.is_symlink():
            raise BootstrapError(f"refusing occupied restore staging path: {staged}")
        try:
            if kind == "symlink":
                link_target = entry.get("target")
                if not isinstance(link_target, str):
                    raise BootstrapError(f"backup symlink target is missing for {target}")
                staged.symlink_to(link_target)
            else:
                source = _backup_entry_source(root, entry)
                if source is None:
                    raise BootstrapError(f"backup payload is missing for {target}")
                if kind == "directory":
                    shutil.copytree(source, staged, symlinks=True)
                elif kind == "file":
                    shutil.copy2(source, staged, follow_symlinks=False)
                else:
                    raise BootstrapError(f"unsupported restore kind {kind!r} for {target}")
            _remove_restore_target(target)
            staged.rename(target)
        finally:
            if staged.exists() or staged.is_symlink():
                _remove_restore_target(staged)


def _path_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(b"symlink\0" + os.readlink(path).encode())
        return digest.hexdigest()
    if path.is_file():
        digest.update(b"file\0" + path.read_bytes())
        return digest.hexdigest()
    if path.is_dir():
        digest.update(b"directory\0")
        for child in sorted(path.rglob("*"), key=lambda item: str(item.relative_to(path))):
            relative = str(child.relative_to(path)).encode()
            digest.update(relative + b"\0")
            if child.is_symlink():
                digest.update(b"symlink\0" + os.readlink(child).encode())
            elif child.is_file():
                digest.update(b"file\0" + child.read_bytes())
            elif child.is_dir():
                digest.update(b"directory\0")
        return digest.hexdigest()
    return "absent"


def _verify_restored_manifest(manifest: dict[str, Any]) -> None:
    root = Path(str(manifest["manifest_path"])).parent
    for entry in manifest["entries"]:
        target = Path(str(entry["path"])).expanduser()
        kind = str(entry["kind"])
        shared_handler = _shared_restore_handler(target)
        source = _backup_entry_source(root, entry)
        if shared_handler == "hooks":
            current = _load_json(target).get("hooks", {})
            previous = (_load_json(source).get("hooks", {}) if source else {})
            current_play = {
                event: [item for item in entries if _is_play_hook(item)]
                for event, entries in current.items()
                if isinstance(entries, list)
                and any(_is_play_hook(item) for item in entries)
            }
            previous_play = {
                event: [item for item in entries if _is_play_hook(item)]
                for event, entries in previous.items()
                if isinstance(entries, list)
                and any(_is_play_hook(item) for item in entries)
            }
            if current_play != previous_play:
                raise BootstrapError(f"restore verification failed for hooks: {target}")
            continue
        if shared_handler == "codex_config":
            current_text = target.read_text(encoding="utf-8") if target.is_file() else ""
            previous_text = source.read_text(encoding="utf-8") if source else ""
            if _play_toml_blocks(current_text) != _play_toml_blocks(previous_text):
                raise BootstrapError(f"restore verification failed for Codex config: {target}")
            continue
        if shared_handler == "plugin_registry":
            current_json = _load_json(target)
            previous_json = _load_json(source) if source else {}
            if _merge_play_plugin_json({}, current_json) != _merge_play_plugin_json(
                {}, previous_json
            ):
                raise BootstrapError(
                    f"restore verification failed for plugin registry: {target}"
                )
            continue
        if kind == "absent":
            if target.exists() or target.is_symlink():
                raise BootstrapError(f"restore verification found unexpected path: {target}")
            continue
        if kind == "symlink":
            if not target.is_symlink() or os.readlink(target) != entry.get("target"):
                raise BootstrapError(f"restore verification failed for symlink: {target}")
            continue
        backup = root / str(entry["backup"])
        if _path_fingerprint(target) != _path_fingerprint(backup):
            raise BootstrapError(f"restore verification failed for: {target}")


def _rollback_play_state(manifest_path: Path) -> Step:
    """Restore and verify the pre-install Play snapshot after a failed update."""

    try:
        manifest = _load_backup_manifest(manifest_path)
        _restore_manifest_entries(manifest)
        _verify_restored_manifest(manifest)
    except (BootstrapError, OSError) as error:
        return Step(
            "rollback_play_state",
            "failed",
            f"Automatic rollback failed: {error}",
            changed=False,
            evidence=str(manifest_path),
        )
    return Step(
        "rollback_play_state",
        "completed",
        "The Play update did not verify; restored and verified the previous Play state.",
        changed=True,
        evidence=str(manifest_path),
    )


def _write_restore_report(report: dict[str, Any]) -> tuple[Path, Path]:
    root = _report_root() / "runs"
    json_path = root / f"{report['restore_id']}.json"
    markdown_path = root / f"{report['restore_id']}.md"
    if json_path.exists() or markdown_path.exists():
        raise BootstrapError(f"restore report already exists: {report['restore_id']}")
    _atomic_json(json_path, report)
    lines = [
        "# Play restore report",
        "",
        f"- Restore: `{report['restore_id']}`",
        f"- Status: **{report['status']}**",
        f"- Restored backup: `{report['backup_run_id']}`",
        f"- Safety backup: `{report['safety_backup_run_id']}`",
        f"- Started: {report['started_at']}",
        f"- Finished: {report['finished_at']}",
        "",
        "## Restored harnesses",
        "",
        *[f"- {item}" for item in report["selected_harnesses"]],
    ]
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    markdown_path.chmod(0o600)
    return json_path, markdown_path


def restore_play_state(plan: dict[str, Any]) -> dict[str, Any]:
    """Transactionally restore an immutable install snapshot and verify it."""

    if plan.get("schema") != RESTORE_PLAN_SCHEMA:
        raise BootstrapError("invalid Play restore plan")
    manifest_path = Path(str(plan["manifest_path"]))
    manifest = _load_backup_manifest(manifest_path)
    if _manifest_sha256(manifest_path) != plan.get("manifest_sha256"):
        raise BootstrapError("Play restore plan is stale; rebuild it before restoring")
    started = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    restore_id = f"restore-{stamp}"
    safety_run_id = f"pre-{restore_id}"
    paths = [Path(str(entry["path"])) for entry in manifest["entries"]]
    safety_manifest_path = _backup_state_paths(
        paths,
        manifest["selected_harnesses"],
        run_id=safety_run_id,
        purpose="pre_restore",
        source_backup_run_id=str(manifest["run_id"]),
    )
    safety_manifest = _load_backup_manifest(safety_manifest_path)
    try:
        _restore_manifest_entries(manifest)
        _verify_restored_manifest(manifest)
    except Exception as error:
        try:
            _restore_manifest_entries(safety_manifest)
            _verify_restored_manifest(safety_manifest)
        except Exception as rollback_error:
            raise BootstrapError(
                f"restore failed ({error}); safety rollback also failed ({rollback_error})"
            ) from rollback_error
        raise BootstrapError(
            f"restore failed and current state was recovered from {safety_manifest_path}: {error}"
        ) from error
    removed = prune_play_backups(
        protect=[str(manifest["run_id"]), safety_run_id]
    )
    report = {
        "schema": RESTORE_REPORT_SCHEMA,
        "restore_id": restore_id,
        "plan_id": plan["plan_id"],
        "status": "completed",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "backup_run_id": manifest["run_id"],
        "backup_manifest": str(manifest_path),
        "safety_backup_run_id": safety_run_id,
        "safety_backup_manifest": str(safety_manifest_path),
        "selected_harnesses": manifest["selected_harnesses"],
        "restored_entries": len(manifest["entries"]),
        "pruned_backup_run_ids": removed,
        "restart": "Restart every restored running harness so it reloads skills and hooks.",
    }
    json_path, markdown_path = _write_restore_report(report)
    return {
        **report,
        "report_paths": {"json": str(json_path), "markdown": str(markdown_path)},
    }


def _render_backup_catalog(catalog: dict[str, Any]) -> str:
    backups = catalog.get("backups", [])
    if not backups:
        return "No Play recovery points found."
    lines = [
        f"Play recovery points — newest {catalog['retention']} retained",
        "",
    ]
    for item in backups:
        harnesses = ", ".join(item["selected_harnesses"]) or "none"
        lines.append(
            f"{item['run_id']}  {item.get('created_at') or 'unknown time'}  "
            f"{item.get('purpose', 'install')}  [{harnesses}]"
        )
    lines.extend(
        [
            "",
            "Inspect one:",
            "  play-bootstrap backup show <run-id>",
        ]
    )
    return "\n".join(lines)


def _render_backup_manifest(manifest: dict[str, Any]) -> str:
    existing = sum(
        1 for entry in manifest["entries"] if entry.get("kind") != "absent"
    )
    lines = [
        f"Play recovery point {manifest['run_id']}",
        f"Created: {manifest.get('created_at') or 'unknown'}",
        f"Purpose: {manifest.get('purpose', 'install')}",
        f"Harnesses: {', '.join(manifest['selected_harnesses']) or 'none'}",
        f"State: {existing} existing paths, {len(manifest['entries']) - existing} absent paths",
        f"Manifest: {manifest['manifest_path']}",
        "",
        "Build a restore plan:",
        f"  play-bootstrap restore --backup {manifest['run_id']} --plan",
    ]
    return "\n".join(lines)


def _render_restore_plan(plan: dict[str, Any]) -> str:
    restores = sum(1 for entry in plan["entries"] if entry["action"] == "restore")
    removals = len(plan["entries"]) - restores
    source = (
        f"Dossier: {plan['dossier_path']}"
        if plan.get("dossier_path")
        else f"Backup: {plan['backup_run_id']}"
    )
    return "\n".join(
        [
            "Play restore plan",
            f"Plan: {plan['plan_id']}",
            source,
            f"Harnesses: {', '.join(plan['selected_harnesses']) or 'none'}",
            f"Changes: restore {restores} paths; remove {removals} paths absent in the snapshot",
            f"Safety: {plan['safety']}",
            "",
            "Apply this plan by rerunning the command without --plan; you will be asked to confirm.",
        ]
    )


def _render_restore_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Play restore completed",
            f"Restored: {report['backup_run_id']}",
            f"Safety backup: {report['safety_backup_run_id']}",
            f"Paths restored: {report['restored_entries']}",
            f"Report: {report['report_paths']['markdown']}",
            report["restart"],
        ]
    )


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Play bootstrap report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Status: **{report['status']}**",
        f"- Plan: `{report['plan_id']}`",
        f"- Started: {report['started_at']}",
        f"- Finished: {report['finished_at']}",
        "",
        "## Selected harnesses",
        "",
    ]
    system = report.get("os")
    if isinstance(system, dict) and system.get("display"):
        lines.insert(7, f"- OS: {system['display']}")
    lines.extend(f"- {name}" for name in report["selected_harnesses"])
    targets = [
        target for target in report.get("targets", []) if isinstance(target, dict)
    ]
    if targets:
        lines.extend(["", "## Harness inventory", ""])
        for target in targets:
            harness = str(target.get("id") or "unknown")
            label = LABELS.get(harness, harness)
            if target.get("selected") is True:
                state = "selected"
            elif target.get("detected") is True:
                state = "detected, not selected"
            else:
                state = "skipped, not installed"
            lines.append(f"- **{label}**: {state}")
    play = report.get("play", {})
    rote = report.get("rote", {})
    tulving = report.get("tulving", {})
    if isinstance(play, dict):
        lines.extend(
            [
                "",
                "## Component versions",
                "",
                f"- Play: {_version_transition(play.get('before'), play.get('after'))}",
                f"- Rote: {_version_transition(rote.get('before'), rote.get('after'))}",
                f"- Tulving: {_version_transition(tulving.get('before'), tulving.get('after'))}",
            ]
        )
    lines.extend(["", "## Steps", ""])
    for step in report["steps"]:
        target = f" ({step['target']})" if step.get("target") else ""
        lines.append(f"- **{step['status']}** `{step['id']}`{target}: {step['detail']}")
    if isinstance(tulving, dict) and isinstance(tulving.get("after"), dict):
        after = tulving["after"]
        if after.get("ready") is True:
            recurring = "ready"
        elif tulving.get("requested") is True and report.get("status") == "rolled_back":
            recurring = "not reached because the Play update rolled back"
        else:
            recurring = "off"
        lines.extend(["", "## Recurring Plays", "", f"- Tulving: **{recurring}**"])
    lines.extend(["", "## Restart", "", report["restart"]])
    backup = report.get("backup")
    if isinstance(backup, dict) and backup.get("restore_command"):
        lines.extend(
            [
                "",
                "## Recovery",
                "",
                f"- Backup: `{backup.get('manifest_path')}`",
                f"- Restore: `{backup.get('restore_command')}`",
                f"- Retention: newest {BACKUP_RETENTION} verified snapshots",
            ]
        )
    report_paths = report.get("report_paths")
    if isinstance(report_paths, dict):
        lines.extend(
            [
                "",
                "## Saved reports",
                "",
                f"- JSON: `{report_paths.get('json')}`",
                f"- Markdown: `{report_paths.get('markdown')}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _post_install_tutorial(selected_harnesses: list[str]) -> list[str]:
    """Render the first-use contract after a successful local installation."""

    lines = [
        "",
        "  Understand Play — optional",
        "",
        "    Rote turns a successful agent run into an inspectable, repeatable Play that can travel across harnesses, models, machines, and teams.",
        "    Want the two-minute tour? Type `play guide` in any ready agent.",
        "    You can also use that agent's native command:",
    ]
    for harness in selected_harnesses:
        launch = HARNESS_LAUNCH.get(str(harness))
        if launch is None:
            continue
        _, invocation = launch
        lines.append(f"       {LABELS[harness]:<28} {invocation} guide")
    lines.extend(
        [
            "",
            "    The guide explains What's New, Hello, running someone else's Play,",
            "    where Plays come from, creating your own, sharing, and repeating later.",
            "",
            "  Or start working",
            "    Ask your agent for the outcome you want.",
            "    Match → inspect and approve → verified result",
            "    No match → Play steps aside → your agent continues normally",
        ]
    )
    return lines


def _reported_version(snapshot: object) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("version")
    if not isinstance(value, str) or not value:
        return None
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", value)
    return match.group(1) if match is not None else value


def _version_transition(before: object, after: object) -> str:
    previous = _reported_version(before)
    current = _reported_version(after)
    if previous and current and previous != current:
        return f"{previous} → {current}"
    if current:
        return current
    if previous:
        return f"{previous} preserved"
    return "not installed"


def _wrap_terminal_card_line(line: str, width: int) -> list[str]:
    if not line:
        return [""]
    leading = len(line) - len(line.lstrip(" "))
    prefix = " " * min(leading, max(0, width - 1))
    content = line.lstrip(" ")
    available = max(1, width - len(prefix))
    return textwrap.wrap(
        content,
        width=available,
        initial_indent=prefix,
        subsequent_indent=prefix,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    ) or [prefix]


def _terminal_card(
    title: str,
    lines: Sequence[str],
    *,
    width: int = TERMINAL_CARD_WIDTH,
) -> str:
    width = max(40, width)
    inner_width = width - 4
    title_segment = f"─ ◆ {title} "
    top = "╭" + title_segment + "─" * max(0, width - len(title_segment) - 2) + "╮"
    body: list[str] = []
    for line in lines:
        for wrapped in _wrap_terminal_card_line(line, inner_width):
            body.append(f"│ {wrapped:<{inner_width}} │")
    bottom = "╰" + "─" * (width - 2) + "╯"
    return "\n".join([top, *body, bottom])


def _update_display(status: object) -> tuple[str, str]:
    normalized = str(status or "unknown").lower()
    if normalized == "current":
        return "✓", "CURRENT · checked"
    if normalized in {"available", "update_available", "outdated"}:
        return "↑", "UPDATE AVAILABLE · checked"
    if normalized == "not_installed":
        return "+", "NOT INSTALLED"
    if normalized == "check_failed":
        return "!", "UPDATE CHECK FAILED"
    if normalized == "repair_required":
        return "!", "REPAIR REQUIRED"
    return "·", normalized.upper()


def _component_version(value: object) -> str:
    return _reported_version(value) or "not installed"


def _display_path(value: object) -> str:
    text = str(value or "")
    home = str(_home())
    if text == home:
        return "~"
    if text.startswith(home + os.sep):
        return "~" + text[len(home) :]
    return text


def _display_restore_command(command: str) -> str:
    marker = "play-bootstrap restore"
    index = command.find(marker)
    compact = command[index:] if index >= 0 else command
    return compact.replace(str(_home()), "~")


def _update_receipt_line(
    label: str,
    command_text: str,
    update: object,
) -> str:
    if isinstance(update, dict) and update.get("check_command"):
        return f"    ✓ {label:<9} {command_text}"
    if isinstance(update, dict) and update.get("status") == "not_installed":
        return f"    · {label:<9} skipped · not installed"
    return f"    · {label:<9} update check not recorded"


def _render_status_card(report: dict[str, Any]) -> str:
    """Render the curl installer's concise, action-oriented final screen."""

    status = str(report["status"])
    status_label = {
        "completed": "READY",
        "onboarding_required": "SETUP PAUSED — SIGN IN REQUIRED",
        "action_required": "READY — ACTION REQUIRED",
        "rolled_back": "UPDATE FAILED — PREVIOUS VERSION RESTORED",
        "blocked": "INCOMPLETE",
    }.get(status, status.upper())
    steps = [step for step in report["steps"] if isinstance(step, dict)]
    onboarding_steps = [
        step for step in steps if step.get("status") == "onboarding_required"
    ]
    general_blocker = any(
        step.get("status") in {"failed", "approval_required"}
        and step.get("target") is None
        for step in steps
    )
    lines = [
        f"  Status: {status_label}",
        f"  Run:    {report['run_id']}",
        "",
        "  Apps",
    ]
    system = report.get("os")
    if isinstance(system, dict) and system.get("display"):
        lines.insert(2, f"  OS:     {system['display']}")
    for harness in report["selected_harnesses"]:
        harness_steps = [step for step in steps if step.get("target") == harness]
        if status == "rolled_back":
            state = "RESTORED"
        elif onboarding_steps:
            state = "WAITING FOR SIGN-IN"
        elif general_blocker or any(
            step.get("status") in {"failed", "approval_required"}
            for step in harness_steps
        ):
            state = "INCOMPLETE"
        elif any(
            step.get("status")
            in {"human_action_required", "review_required", "onboarding_required"}
            for step in harness_steps
        ):
            state = "ACTION REQUIRED"
        else:
            state = "READY"
        state_icon = "✓" if state == "READY" else ("↺" if state == "RESTORED" else "!")
        lines.append(f"    {state_icon} {LABELS.get(harness, harness):<14} {state}")

    play = report.get("play", {})
    rote = report.get("rote", {})
    tulving = report.get("tulving", {})
    if isinstance(play, dict):
        play_mode = str(play.get("install_state") or "unknown").upper()
        rote_before = rote.get("before", {}) if isinstance(rote, dict) else {}
        rote_update = (
            rote_before.get("update", {}) if isinstance(rote_before, dict) else {}
        )
        tulving_before = (
            tulving.get("before", {}) if isinstance(tulving, dict) else {}
        )
        tulving_update = (
            tulving_before.get("update", {})
            if isinstance(tulving_before, dict)
            else {}
        )
        rote_icon, rote_state = _update_display(
            rote_update.get("status") if isinstance(rote_update, dict) else None
        )
        tulving_icon, tulving_state = _update_display(
            tulving_update.get("status") if isinstance(tulving_update, dict) else None
        )
        lines.extend(
            [
                "",
                "  Components",
                f"    ✓ Play       {_version_transition(play.get('before'), play.get('after'))} · {play_mode}",
                f"    {rote_icon} Rote       {_version_transition(rote.get('before'), rote.get('after'))} · {rote_state}",
                f"    {tulving_icon} Tulving    {_version_transition(tulving.get('before'), tulving.get('after'))} · {tulving_state}",
                "",
                "  Update receipts",
                _update_receipt_line(
                    "Rote", "rote self-update --check", rote_update
                ),
                _update_receipt_line(
                    "Tulving", "tulving update --check", tulving_update
                ),
            ]
        )

    after = tulving.get("after", {}) if isinstance(tulving, dict) else {}
    if isinstance(after, dict) and after.get("ready") is True:
        recurring_state = "READY"
    elif tulving.get("requested") is True and status == "rolled_back":
        recurring_state = "NOT REACHED — UPDATE ROLLED BACK"
    else:
        recurring_state = "OFF"
    lines.extend(["", f"  Recurring Plays   {recurring_state}"])

    targets = [
        target for target in report.get("targets", []) if isinstance(target, dict)
    ]
    skipped = [target for target in targets if target.get("detected") is not True]
    not_selected = [
        target
        for target in targets
        if target.get("detected") is True and target.get("selected") is not True
    ]
    if skipped:
        lines.extend(["", "  Skipped — not installed"])
        for target in skipped:
            harness = str(target.get("id") or "unknown")
            lines.append(f"    {LABELS.get(harness, harness)}")
    if not_selected:
        lines.extend(["", "  Detected — not selected"])
        for target in not_selected:
            harness = str(target.get("id") or "unknown")
            lines.append(f"    {LABELS.get(harness, harness)}")

    action_steps = [
        step
        for step in steps
        if step.get("status")
        in {"failed", "approval_required", "human_action_required", "review_required"}
    ]
    if onboarding_steps:
        remote_handoff = any(
            step.get("evidence") == REMOTE_AUTH_EVIDENCE
            for step in onboarding_steps
        )
        if remote_handoff:
            lines.extend(
                [
                    "",
                    "  Sign in from another machine",
                    "    On a machine with a browser:",
                    "      1. Run `rote login --provider google` or `rote login --provider github`.",
                    "      2. Run `rote provision --ttl 30` and copy the generated claim token.",
                    "    On this machine:",
                    "      3. Run `rote claim <dxp_...>`, then verify with `rote whoami`.",
                    "      4. Re-run this Play installer.",
                    "    Treat the claim token as a password; never paste it into chat or logs.",
                    "    Play-owned harness state has not been changed.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "  Sign in to finish setup",
                    "    Re-run this installer in a terminal and choose Google or GitHub.",
                    "    Headless machine? Use `rote provision` elsewhere, then `rote claim` here.",
                    "    For unattended browser sign-in, pass PLAY_LOGIN_PROVIDER=google or github.",
                    "    Play-owned harness state has not been changed.",
                ]
            )
    if action_steps:
        lines.extend(["", "  Before you start"])
        for step in action_steps:
            target = step.get("target")
            if target:
                prefix = f"{LABELS.get(str(target), str(target))}: "
            else:
                step_id = str(step.get("id") or "setup")
                prefix = step_id.replace("_", " ").title() + ": "
            lines.append(f"    - {prefix}{_human_step_detail(step)}")

    if status == "rolled_back":
        lines.extend(
            [
                "",
                "  Previous version restored",
                "    The replacement did not pass verification.",
                "    Play restored and verified the pre-update snapshot automatically.",
                "    Review the detailed report, then restart the harness.",
            ]
        )

    if status not in {"blocked", "onboarding_required", "rolled_back"}:
        if status == "action_required":
            lines.extend(
                [
                    "",
                    "  Complete the action above before asking for the guide.",
                ]
            )
        lines.extend(_post_install_tutorial(report["selected_harnesses"]))
        lines.extend(["", "  Browse Plays"])
        for harness in report["selected_harnesses"]:
            launch = HARNESS_LAUNCH.get(str(harness))
            if launch is None:
                continue
            command, invocation = launch
            label = LABELS.get(str(harness), str(harness))
            if harness == "codex":
                lines.append(f'    {label}: codex "\\$play what\'s new"')
            elif harness == "claude":
                lines.append(f'    {label}: claude "/play what\'s new"')
            else:
                lines.append(f"    {label}: start `{command}`, then type `{invocation} what's new`")

    report_paths = report.get("report_paths")
    if isinstance(report_paths, dict):
        lines.extend(
            [
                "",
                "  Detailed report",
                f"    {_display_path(report_paths.get('markdown'))}",
                f"    {_display_path(report_paths.get('json'))}",
            ]
        )
    backup = report.get("backup")
    if (
        isinstance(backup, dict)
        and backup.get("has_previous_state") is True
        and isinstance(backup.get("restore_command"), str)
    ):
        recovery_summary = (
            "The current Play state was snapshotted before verification."
            if isinstance(play, dict) and play.get("install_state") == "verify"
            else "The previous Play state was snapshotted before convergence."
        )
        lines.extend(
            [
                "",
                "  Recovery point",
                f"    {recovery_summary}",
                "    To review and restore it:",
                f"    {_display_restore_command(str(backup['restore_command']))}",
                f"    Play retains the newest {BACKUP_RETENTION} verified recovery points.",
            ]
        )
    play_mode = (
        str(play.get("install_state") or "unknown")
        if isinstance(play, dict)
        else "unknown"
    )
    pro_tip = {
        "fresh": "Rerun this installer later to verify the same Play version.",
        "verify": "A current install stays in place unless Play detects file drift.",
        "update": "The recovery command above can restore the pre-update snapshot.",
        "repair": "The damaged state was snapshotted before missing files were restored.",
    }.get(play_mode, "Detailed JSON and Markdown receipts preserve the full setup evidence.")
    lines.extend(
        [
            "",
            f"  ✦ Pro tip · {pro_tip}",
            "",
            "  ☕ Easter egg · Watch the agent's route unfold",
            "    Run `play journey view --active`.",
            "    Choose the active workspace on the left, press Play, then grab a coffee.",
        ]
    )
    return "\n" + _terminal_card("Play setup", lines) + "\n"


def _human_step_detail(step: dict[str, Any]) -> str:
    detail = str(step.get("detail") or "Review the saved report.").strip()
    try:
        structured = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        structured = None
    if isinstance(structured, (dict, list)):
        return "Command output was captured; see the detailed JSON report."
    stderr_marker = "stderr:\n"
    if detail.startswith(stderr_marker) or f"\n\n{stderr_marker}" in detail:
        stderr = detail.rsplit(stderr_marker, 1)[1].strip()
        if stderr:
            detail = stderr
    nonempty = [line.strip() for line in detail.splitlines() if line.strip()]
    if len(nonempty) > 3 or len(detail) > 240:
        summary = nonempty[0] if nonempty else "Command output was captured."
        if len(summary) > 180:
            summary = summary[:177].rstrip() + "..."
        return summary + " See the detailed report for complete output."
    return " ".join(nonempty) if nonempty else "Review the saved report."


def _render_plan(plan: dict[str, Any]) -> str:
    play = plan.get("play", {})
    play_mode = (
        str(play.get("install_state") or "unknown").upper()
        if isinstance(play, dict)
        else "UNKNOWN"
    )
    lines = [
        f"  Review: READY TO APPLY · {play_mode}",
        f"  Version: {plan.get('play_version', 'unknown')}",
        "",
        "  Components",
    ]
    if isinstance(play, dict):
        installed = str(play.get("installed_version") or "not installed")
        target = str(play.get("target_version") or "unknown")
        transition = target if installed == target else f"{installed} → {target}"
        play_icon = "✓" if play_mode == "VERIFY" else ("!" if play_mode == "REPAIR" else "↑")
        lines.append(
            f"    {play_icon} Play       {transition:<22} {play_mode}"
        )
    rote = plan["rote"]
    update = rote["update"]
    rote_icon, rote_update = _update_display(update.get("status"))
    lines.append(
        f"    {rote_icon} Rote       {str(rote.get('version') or 'not installed'):<22} {rote_update}"
    )
    tulving = plan.get("tulving", {})
    tulving_update = tulving.get("update", {}) if isinstance(tulving, dict) else {}
    if isinstance(tulving_update, dict):
        tulving_icon, tulving_status = _update_display(tulving_update.get("status"))
        installed_tulving = str(
            tulving_update.get("installed")
            or _reported_version(tulving)
            or "not installed"
        )
        latest_tulving = tulving_update.get("latest")
        tulving_version = (
            f"{installed_tulving} → {latest_tulving}"
            if tulving_update.get("status") == "available" and latest_tulving
            else installed_tulving
        )
        clock = "clock ready" if tulving.get("ready") is True else "clock off"
        lines.append(
            f"    {tulving_icon} Tulving    {tulving_version:<22} {tulving_status} · {clock}"
        )
    lines.extend(["", "  Update checks"])
    lines.append(_update_receipt_line("Rote", "rote self-update --check", update))
    lines.append(
        _update_receipt_line(
            "Tulving", "tulving update --check", tulving_update
        )
    )
    lines.extend(["", "  Apps"])
    skill_states = {
        str(item["provider"]): item
        for item in plan["rote_skills"]
        if isinstance(item, dict) and item.get("provider")
    }
    skill_labels = {
        str(item["label"]): item
        for item in plan["rote_skills"]
        if isinstance(item, dict) and item.get("label")
    }
    skill_action = next(
        (
            action
            for action in plan["actions"]
            if action.get("id") == "converge_rote_skills"
        ),
        {},
    )
    targeted_skill_providers = {
        TARGET_IDS[str(harness)]
        for harness in skill_action.get("targets", [])
        if str(harness) in TARGET_IDS
    }
    for harness in plan["selected_harnesses"]:
        target = TARGET_IDS[str(harness)]
        label = LABELS.get(str(harness), str(harness))
        item = skill_states.get(target, skill_labels.get(label, {}))
        if target in targeted_skill_providers:
            state = "REFRESH" if item.get("installed") else "INSTALL"
        else:
            state = "CURRENT"
        state_icon = "✓" if state == "CURRENT" else ("↑" if state == "REFRESH" else "+")
        lines.append(f"    {state_icon} {label:<27} Rote skills · {state}")
    lines.extend(
        [
            "",
            "  Changes",
            "    1. Verify the Rote identity and component update receipts.",
            "    2. Snapshot prior Play-owned state before convergence.",
            "    3. Prepare selected skill roots while preserving unrelated entries.",
            "    4. Converge Play files, hooks, launchers, and the public Play cache.",
            "    5. Verify each app and roll back automatically if verification fails.",
            "",
            "  Safety",
            "    ✓ Preserve unrelated harness settings and shared skill entries.",
            "    ✓ Keep a recovery point before changing existing Play state.",
            "    ✓ Roll back automatically when verification fails.",
        ]
    )
    approvals = [action for action in plan["actions"] if action.get("approval_required")]
    if approvals:
        lines.extend(["", "  Separate approval"])
        if any(action.get("id") == "install_rote" for action in approvals):
            lines.append(
                "    Installing Rote uses its official remote installer; approval is checked before execution."
            )
        if any(str(action.get("id", "")).endswith("tulving") for action in approvals):
            lines.append(
                "    Tulving installation, update, or clock initialization requires separate approval."
            )
    lines.extend(
        [
            "",
            "  Locations",
            f"    Rote      {_display_path(rote.get('path')) if rote.get('path') else 'not installed'}",
            f"    Tulving   {_display_path(tulving.get('executable')) if isinstance(tulving, dict) and tulving.get('executable') else 'not installed'}",
            "",
            "  Plan ID",
            f"    {plan['plan_id']}",
            "  ✦ Pro tip · Press Enter to accept the recommended setup; detailed mode changes presentation, not safety.",
        ]
    )
    return "\n" + _terminal_card("Review setup", lines) + "\n"


def _render_guided_plan(plan: dict[str, Any]) -> str:
    play = plan.get("play", {})
    play_status = str(play.get("update_status") or "unknown") if isinstance(play, dict) else "unknown"
    if play_status == "not_installed":
        play_summary = f"Install Play {plan.get('play_version', 'unknown')}"
    elif play_status == "available":
        play_summary = f"Update Play to {plan.get('play_version', 'unknown')}"
    elif play_status == "repair_required":
        play_summary = f"Repair Play {plan.get('play_version', 'unknown')} from a recovery snapshot"
    else:
        play_summary = f"Verify Play {plan.get('play_version', 'unknown')}"
    rote = plan["rote"]
    update_status = str(rote["update"]["status"]).lower()
    if rote["path"] is None:
        rote_summary = "Install the official Rote engine"
    elif update_status in {"available", "update_available", "outdated"}:
        rote_summary = "Update the Rote engine"
    else:
        rote_summary = "Keep the current Rote engine"
    apps = " · ".join(
        LABELS.get(str(harness), str(harness))
        for harness in plan["selected_harnesses"]
    )
    app_count = len(plan["selected_harnesses"])
    app_word = "app" if app_count == 1 else "apps"
    convergence_summary = {
        "fresh": "Install Play-owned app state while preserving unrelated settings",
        "verify": "Keep current Play files in place and repair only detected drift",
        "update": "Snapshot the current version, then update Play-owned app state",
        "repair": "Snapshot the damaged state, then restore missing Play-owned files",
    }.get(
        str(play.get("install_state") or "unknown")
        if isinstance(play, dict)
        else "unknown",
        "Converge Play-owned app state while preserving unrelated settings",
    )
    lines = [
            f"    Play   {play_summary}",
            f"    Rote   {rote_summary}",
            f"    Apps   {apps}",
    ]
    tulving = plan.get("tulving", {})
    tulving_update = tulving.get("update", {}) if isinstance(tulving, dict) else {}
    if (
        isinstance(tulving, dict)
        and tulving.get("ready") is True
        and isinstance(tulving_update, dict)
        and tulving_update.get("status") == "available"
    ):
        lines.append(
            "    Repeat Update Tulving "
            f"{tulving_update.get('installed')} → {tulving_update.get('latest')} "
            "after separate approval"
        )
    elif isinstance(tulving, dict) and tulving.get("ready") is True:
        lines.append("    Repeat Tulving is ready for optional recurring Plays")
    else:
        lines.append("    Repeat Optional; setup asks before enabling Tulving")
    shared_agents = plan.get("shared_agents", {})
    shared_targets = (
        shared_agents.get("targets", [])
        if isinstance(shared_agents, dict)
        else []
    )
    if shared_targets:
        shared_action = "Create" if shared_agents.get("will_create") else "Update"
        lines.extend(
            [
                f"    Shared {shared_action} {shared_agents['path']} for compatible apps",
                "           Preserve every unrelated entry in that shared root",
            ]
        )
    lines.extend(
        [
            "",
            "  What happens next",
            "",
            "    1. Verify your Rote identity; headless machines can claim credentials provisioned elsewhere",
            "    2. Cache a verified public Play catalog for What’s New",
            f"    3. Prepare Rote and its skills for {app_count} {app_word}",
            f"    4. {convergence_summary}",
            "    5. Verify every app and save a detailed receipt",
        ]
    )
    recovery = plan.get("recovery", {})
    existing = (
        recovery.get("existing_recovery_points", 0)
        if isinstance(recovery, dict)
        else 0
    )
    if isinstance(existing, int) and existing > 0:
        lines.extend(
            [
                "",
                f"  Recovery   {existing} existing point{'s' if existing != 1 else ''}; newest {BACKUP_RETENTION} retained",
            ]
        )
    lines.extend(
        [
            "",
            "  Credentials stay on this machine. Plays disclose writes before they run.",
        ]
    )
    return "\n" + _terminal_card("Quick review", lines) + "\n"


def _confirm(question: str, *, default: bool) -> bool:
    """Read an approval from the controlling terminal, even when the installer is piped."""

    prompt = " [Y/n] " if default else " [y/N] "
    stream = None
    close_stream = False
    if sys.stdin.isatty():
        stream = sys.stdin
    else:
        try:
            stream = open("/dev/tty", "r+", encoding="utf-8")
            close_stream = True
        except OSError as error:
            raise BootstrapError(
                "guided setup needs an interactive terminal. Run "
                "'curl -fsSL https://getrote.dev/playoffs/install.sh | sh' in a "
                "terminal; CI may explicitly set PLAY_INSTALL_YES=1 and "
                "PLAY_APPROVE_REMOTE_INSTALLER=1"
            ) from error
    try:
        if stream is sys.stdin:
            print(question + prompt, end="", file=sys.stderr, flush=True)
        else:
            stream.write(question + prompt)
            stream.flush()
        answer = stream.readline()
    finally:
        if close_stream:
            stream.close()
    if not answer:
        raise BootstrapError("interactive approval ended before a choice was received")
    normalized = answer.strip().lower()
    if not normalized:
        return default
    if normalized in {"y", "yes"}:
        return True
    if normalized in {"n", "no"}:
        return False
    raise BootstrapError("approval must be yes or no")


def _login_method_options(browser_mode: str) -> tuple[tuple[str, str], ...]:
    if browser_mode == "headless":
        return (
            ("remote", "Sign in from another machine"),
            ("google", "Continue with Google using an SSH-forwarded callback"),
            ("github", "Continue with GitHub using an SSH-forwarded callback"),
            ("exit", "Exit setup"),
        )
    return (
        ("google", "Continue with Google"),
        ("github", "Continue with GitHub"),
        ("remote", "Sign in from another machine"),
        ("exit", "Exit setup"),
    )


def _update_login_picker(
    key: str,
    option_count: int,
    active_index: int,
) -> tuple[int, str | None, str | None]:
    if option_count < 1:
        return 0, "cancel", None
    active_index = max(0, min(active_index, option_count - 1))
    if key == "up":
        active_index = (active_index - 1) % option_count
    elif key == "down":
        active_index = (active_index + 1) % option_count
    elif key in {"toggle", "confirm"}:
        return active_index, "confirm", None
    elif key == "cancel":
        return active_index, "cancel", None
    elif key in {"unknown", "all", "clear"}:
        return active_index, None, "Use arrow keys, Space, Enter, or q."
    return active_index, None, None


def _render_login_picker(
    browser_mode: str,
    *,
    active_index: int = 0,
    message: str | None = None,
    width: int | None = None,
) -> str:
    options = _login_method_options(browser_mode)
    active_index = max(0, min(active_index, len(options) - 1))
    lines = [
        "",
        "  Rote sign-in required",
        "",
    ]
    if browser_mode == "headless":
        lines.extend(
            [
                "  No browser was detected on this machine.",
                "  Rote sign-in is mandatory. Setup activates Play only after verification.",
            ]
        )
    else:
        lines.append(
            "  Rote sign-in is mandatory. Setup activates Play only after verification."
        )
    lines.extend(
        [
            "  Choose one method, or exit setup without changing Play-owned state.",
            "  Use ↑/↓ to move, Space or Enter to choose, and q to exit.",
            "",
        ]
    )
    for index, (_, label) in enumerate(options):
        pointer = "❯" if index == active_index else " "
        radio = "●" if index == active_index else "○"
        recommendation = "  recommended" if index == 0 else ""
        lines.append(f"  {pointer} {radio} {label}{recommendation}")
    lines.extend(
        [
            "",
            (
                f"  {message}"
                if message
                else "  Setup continues only after Rote verifies your identity."
            ),
        ]
    )
    return "\n".join(_fit_picker_line(line, width) for line in lines)


def _run_login_picker(browser_mode: str, stream: Any, output: Any) -> str:
    import termios
    import tty

    file_descriptor = stream.fileno()
    try:
        terminal_state = termios.tcgetattr(file_descriptor)
    except termios.error as error:
        raise BootstrapError(
            "sign-in selection needs an interactive terminal; automation must pass "
            "--login-provider google|github or --remote-auth"
        ) from error
    try:
        width = max(20, os.get_terminal_size(output.fileno()).columns - 1)
    except (AttributeError, OSError):
        width = max(20, shutil.get_terminal_size(fallback=(100, 24)).columns - 1)
    options = _login_method_options(browser_mode)
    active_index = 0
    message = None
    previous_line_count = 0
    output.write("\x1b[?25l")
    output.flush()
    try:
        tty.setcbreak(file_descriptor)
        while True:
            frame = _render_login_picker(
                browser_mode,
                active_index=active_index,
                message=message,
                width=width,
            )
            previous_line_count = _redraw_harness_picker(
                output, frame, previous_line_count
            )
            key = _read_harness_picker_key(file_descriptor)
            active_index, outcome, message = _update_login_picker(
                key, len(options), active_index
            )
            if outcome == "confirm":
                method, label = options[active_index]
                final_frame = _render_login_picker(
                    browser_mode,
                    active_index=active_index,
                    message=f"✓ {label} selected.",
                    width=width,
                )
                _redraw_harness_picker(output, final_frame, previous_line_count)
                return method
            if outcome == "cancel":
                return "exit"
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, terminal_state)
        output.write("\x1b[?25h")
        output.flush()


def _choose_login_method(browser_mode: str, *, stream=None) -> str:
    """Choose browser OAuth or a secure handoff from the controlling terminal."""

    close_stream = False
    output = sys.stderr
    if stream is None:
        if sys.stdin.isatty():
            stream = sys.stdin
            if not output.isatty():
                output = stream
        else:
            try:
                stream = open("/dev/tty", "r+", encoding="utf-8")
                output = stream
                close_stream = True
            except OSError as error:
                raise BootstrapError(
                    "sign-in needs an interactive terminal, a pre-claimed Rote identity, "
                    "or --login-provider google|github"
                ) from error
    elif stream is not sys.stdin:
        output = stream
    try:
        return _run_login_picker(browser_mode, stream, output)
    finally:
        if close_stream:
            stream.close()


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    root = _report_root() / "runs"
    json_path = root / f"{report['run_id']}.json"
    markdown_path = root / f"{report['run_id']}.md"
    if json_path.exists() or markdown_path.exists():
        raise BootstrapError(f"report already exists for run {report['run_id']}")
    _atomic_json(json_path, report)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    markdown_path.chmod(0o600)
    return json_path, markdown_path


def apply(
    source: Path,
    *,
    top_k: int = 3,
    requested: Sequence[str] | None = None,
    approve_remote_installer: bool = False,
    enable_tulving: bool = False,
    login_provider: str | None = None,
    remote_auth: bool = False,
    runner: Runner = run,
    run_id: str | None = None,
    expected_plan_id: str | None = None,
    prepared_plan: dict[str, Any] | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    started = datetime.now(timezone.utc).isoformat()
    active_progress = _progress(progress)
    plan = prepared_plan or active_progress.call(
        "Checking the install plan",
        lambda: build_plan(top_k=top_k, requested=requested, runner=runner),
    )
    if login_provider is not None and remote_auth:
        raise BootstrapError("choose either browser OAuth or remote authentication")
    if expected_plan_id is not None and expected_plan_id != plan["plan_id"]:
        raise BootstrapError(
            f"plan changed: expected {expected_plan_id}, got {plan['plan_id']}"
        )
    plan = {**plan, "enable_tulving_requested": enable_tulving}
    rote_plan = plan.get("rote")
    planned_identity = (
        rote_plan.get("identity") if isinstance(rote_plan, dict) else None
    )
    if (
        planned_identity in {None, "required", "unavailable"}
        and login_provider is None
        and not remote_auth
    ):
        raise BootstrapError(_registry_credentials_blocker())
    selected = list(plan["selected_harnesses"])
    steps: list[Step] = []

    def finish_report(status: str) -> dict[str, Any]:
        active_progress.complete_phase()
        return _finish_report(
            plan, run_id, started, steps, status=status, runner=runner
        )

    rote = resolve_rote()
    initially_present = rote is not None

    if rote is None:
        if not approve_remote_installer:
            steps.append(
                Step(
                    "install_rote",
                    "approval_required",
                    "Approve the official remote installer, then resume with --approve-remote-installer.",
                    command=["bash", "-c", "$(curl -fsSL https://getrote.dev/install)"],
                )
            )
        else:
            command = _official_rote_install_command()
            if active_progress.enabled:
                print("", file=active_progress.stream)
                print("  Installing Rote components", file=active_progress.stream)
                print(
                    "    CLI · Node and Deno runtimes · browser automation · shell integration",
                    file=active_progress.stream,
                )
                print(
                    "    Live component progress follows; details are also saved to ~/.rote/log/install.log.",
                    file=active_progress.stream,
                    flush=True,
                )
            result = _run_visible(command, runner)
            steps.append(_result_step("install_rote", result, command))
            rote = resolve_rote()
            if result.returncode != 0 or rote is None:
                return finish_report("blocked")
    update_status = plan["rote"]["update"]["status"]
    if initially_present and rote is not None and update_status == "available":
        command = [rote, "self-update", "--yes"]
        result = active_progress.command("Updating Rote", runner, command)
        steps.append(_result_step("update_rote", result, command))
        if result.returncode != 0:
            return finish_report("blocked")
    elif initially_present and rote is not None:
        detail = plan["rote"]["update"]["detail"]
        steps.append(
            Step(
                "check_rote_update",
                "unchanged" if update_status == "current" else "review_required",
                detail,
                command=[rote, "self-update", "--check"],
            )
        )

    if rote is None:
        return finish_report("blocked")

    compatibility_step = _rote_compatibility_step(rote, runner)
    steps.append(compatibility_step)
    if compatibility_step.status == "failed":
        return finish_report("blocked")

    identity_step, identity_ready = _identity_gate(
        rote,
        login_provider=login_provider,
        remote_auth=remote_auth,
        runner=runner,
    )
    steps.append(identity_step)
    if identity_step.changed and active_progress.enabled:
        print(f"✓ {identity_step.detail}", file=active_progress.stream, flush=True)
    if not identity_ready:
        return finish_report("onboarding_required")

    active_progress.start_phase("Preparing Play")
    root_step = active_progress.call(
        "Preparing selected harness skill roots",
        lambda: prepare_selected_skill_roots(selected),
    )
    steps.append(root_step)
    if root_step.status == "failed":
        return finish_report("blocked")

    skill_harnesses = _rote_skill_harnesses(
        selected, plan["rote_skills"], update_status
    )
    skill_command = _rote_skill_command(rote, skill_harnesses) if skill_harnesses else None
    missing = [item["label"] for item in plan["rote_skills"] if not item["installed"]]
    refreshed = [item["label"] for item in plan["rote_skills"] if item["installed"]]
    if skill_command is None:
        steps.append(
            Step(
                "converge_rote_skills",
                "unchanged",
                "Selected harnesses already have current Rote skills.",
            )
        )
    else:
        skill_result = active_progress.command(
            f"Converging Rote skills for {len(skill_harnesses)} harness{'es' if len(skill_harnesses) != 1 else ''}",
            runner,
            skill_command,
        )
        coverage = []
        if missing:
            coverage.append("installed " + ", ".join(missing))
        if update_status == "available" and refreshed:
            coverage.append("refreshed " + ", ".join(refreshed))
        skill_output = (skill_result.stdout or skill_result.stderr).strip()
        detail = "; ".join(coverage)
        if skill_output:
            detail = f"{detail}. {skill_output}" if detail else skill_output
        steps.append(
            Step(
                "converge_rote_skills",
                "completed" if skill_result.returncode == 0 else "failed",
                detail or f"exit {skill_result.returncode}",
                command=skill_command,
                changed=skill_result.returncode == 0,
            )
        )
        if skill_result.returncode != 0:
            return finish_report("blocked")

    expected_version = (source / "VERSION").read_text(encoding="utf-8").strip()
    plan_targets = {
        str(target["id"]): target
        for target in plan["targets"]
        if isinstance(target, dict) and isinstance(target.get("id"), str)
    }
    active_progress.start_phase("Protecting existing setup")
    try:
        backup_manifest = active_progress.call(
            "Creating a Play recovery snapshot",
            lambda: backup_play_state(selected, plan_targets, run_id=run_id),
        )
    except Exception as error:
        steps.append(
            Step(
                "backup_play_state",
                "failed",
                str(error),
            )
        )
        return finish_report("blocked")
    steps.append(
        Step(
            "backup_play_state",
            "completed",
            f"Snapshotted detected Play-owned state before convergence: {backup_manifest}",
            changed=True,
            evidence=str(backup_manifest),
        )
    )

    def rollback_failed_update() -> dict[str, Any]:
        active_progress.start_phase("Restoring previous setup")
        rollback_step = active_progress.call(
            "Restoring the previous Play version",
            lambda: _rollback_play_state(backup_manifest),
        )
        steps.append(rollback_step)
        return finish_report(
            "rolled_back" if rollback_step.status == "completed" else "blocked"
        )

    def fail_update(step_id: str, error: Exception) -> dict[str, Any]:
        steps.append(Step(step_id, "failed", str(error)))
        return rollback_failed_update()

    try:
        steps.append(
            active_progress.call(
                "Preparing a clean Play cache rebuild",
                _prepare_derived_play_caches,
            )
        )
    except (BootstrapError, OSError) as error:
        return fail_update("prepare_play_caches", error)

    cache_step = _warm_public_play_cache(
        source,
        runner=runner,
        progress=active_progress,
    )
    steps.append(cache_step)

    for harness in selected:
        target = plan_targets.get(harness, {})
        executable = target.get("command") if isinstance(target, dict) else None
        if not isinstance(executable, str) or not executable:
            steps.append(
                Step(
                    "locate_harness",
                    "human_action_required",
                    f"{LABELS[harness]} is not on PATH as `{HARNESS_COMMANDS[harness]}`. Play files will be prepared, but install or expose the app command before launching it.",
                    target=harness,
                )
            )
    marketplace_harnesses = [
        harness
        for harness in selected
        if harness in {"codex", "claude"}
        and isinstance(plan_targets.get(harness, {}).get("command"), str)
        and plan_targets[harness]["command"]
    ]
    active_progress.start_phase("Connecting selected apps")

    def converge_marketplace(harness: str) -> list[Step]:
        executable = str(plan_targets[harness]["command"])
        token = active_progress.begin(f"Integrating {LABELS[harness]}")
        try:
            result = converge_play_marketplace(
                harness,
                executable,
                expected_version=expected_version,
                expected_plugin_root=(
                    source / "plugins" / "play"
                    if (source / "plugins" / "play").is_dir()
                    else source
                ),
                runner=runner,
            )
        except Exception:
            active_progress.finish(token, ok=False)
            raise
        active_progress.finish(
            token, ok=not any(step.status == "failed" for step in result)
        )
        return result

    try:
        marketplace_results = _parallel_harness_work(
            marketplace_harnesses, converge_marketplace
        )
    except Exception as error:
        return fail_update("converge_play_marketplaces", error)
    for harness in marketplace_harnesses:
        steps.extend(marketplace_results[harness])
    if any(
        step.status == "failed"
        for harness in marketplace_harnesses
        for step in marketplace_results[harness]
    ):
        return rollback_failed_update()

    if "codex" in selected:
        try:
            steps.append(codex_play_enablement_step())
        except Exception as error:
            return fail_update("enable_play_skill", error)

    installer = source / "scripts" / "harness" / "install-all"
    install_command = [
        str(installer),
        "install",
        "--copy",
        "--prepared-backup",
        str(backup_manifest),
    ]
    for harness in selected:
        install_command.extend(["--harness", harness])
    try:
        install_result = active_progress.command(
            f"Activating Play in {len(selected)} harness{'es' if len(selected) != 1 else ''}",
            runner,
            install_command,
        )
    except Exception as error:
        return fail_update("install_play", error)
    steps.append(_result_step("install_play", install_result, install_command))
    if install_result.returncode != 0:
        return rollback_failed_update()

    try:
        steps.append(
            active_progress.call(
                "Installing Journey model telemetry",
                lambda: install_journey_model_assets(source),
            )
        )
    except (BootstrapError, OSError) as error:
        steps.append(Step("install_journey_model_assets", "failed", str(error)))
        return rollback_failed_update()

    installed_source = Path(os.environ.get("PLAY_INSTALL_HOME", source)).expanduser()
    if os.environ.get("PLAY_INSTALL_HOME"):
        installed_source = installed_source.resolve() / "skill"
    else:
        data = Path(os.environ.get("XDG_DATA_HOME", _home() / ".local" / "share")).expanduser()
        installed_source = (data / "modiqo" / "play" / "skill").resolve()
    hook_harnesses = [
        harness
        for harness in selected
        if plan_targets.get(harness, {}).get("hooks") == "managed"
    ]

    def install_harness_hooks(harness: str) -> Step:
        return active_progress.call(
            f"Installing {LABELS[harness]} hooks",
            lambda: install_hooks(
                harness, installed_source, run_id=run_id, verify_catalog=True
            ),
        )

    try:
        hook_results = _parallel_harness_work(hook_harnesses, install_harness_hooks)
    except Exception as error:
        return fail_update("install_hooks", error)
    for harness in selected:
        if harness in hook_results:
            steps.append(hook_results[harness])

    launcher = Path(
        os.environ.get("PLAY_MACHINE_LAUNCHER", _home() / ".local" / "bin" / "play-machine")
    ).expanduser()
    verification_path = os.pathsep.join(
        part for part in (str(launcher.parent), os.environ.get("PATH", "")) if part
    )
    def verify_harness(harness: str) -> subprocess.CompletedProcess[str]:
        command = [
            "env",
            f"PATH={verification_path}",
            str(installed_source / "scripts" / "bin" / "play-preflight"),
            "--harness",
            harness,
            "--json",
        ]
        return active_progress.command(
            f"Verifying {LABELS[harness]}",
            lambda requested: _accept_identity_only_preflight(runner(requested)),
            command,
        )

    active_progress.start_phase("Verifying the installation")
    try:
        verification_results = _parallel_harness_work(selected, verify_harness)
    except Exception as error:
        return fail_update("verify", error)
    for harness in selected:
        command = [
            "env",
            f"PATH={verification_path}",
            str(installed_source / "scripts" / "bin" / "play-preflight"),
            "--harness",
            harness,
            "--json",
        ]
        steps.append(
            _result_step(
                "verify", verification_results[harness], command, target=harness
            )
        )
    tulving_state = plan.get("tulving", {})
    if enable_tulving:
        try:
            tulving_result = active_progress.call(
                "Synchronizing recurring Plays with Tulving",
                lambda: enable_tulving_support(
                    runner=runner,
                    synchronize_update=True,
                ),
            )
            tulving_state = tulving_result
            changed = bool(
                tulving_result.get("installed")
                or tulving_result.get("updated")
                or tulving_result.get("initialized")
            )
            update_error = tulving_result.get("update_error")
            if isinstance(update_error, str) and update_error:
                detail = (
                    "Tulving is ready, but its independent update cycle needs attention: "
                    + update_error
                )
                step_status = "review_required"
            elif tulving_result.get("updated") is True:
                detail = (
                    f"Tulving was updated from {tulving_result.get('previous_version') or 'an earlier version'} "
                    f"to {tulving_result.get('version') or 'the current version'}; its clock is ready."
                )
                step_status = "completed"
            else:
                detail = (
                    "Tulving was installed with Homebrew and its clock is ready."
                    if tulving_result.get("installer") == "homebrew"
                    else (
                        "Tulving was installed with its official installer and its clock is ready."
                        if tulving_result.get("installer") == "official-script"
                        else "Tulving is current and its clock is ready."
                    )
                )
                step_status = "completed" if changed else "unchanged"
            steps.append(
                Step(
                    "enable_tulving",
                    step_status,
                    detail,
                    changed=changed,
                    evidence=json.dumps(tulving_result, sort_keys=True),
                )
            )
        except RecurrenceError as error:
            steps.append(
                Step(
                    "enable_tulving",
                    "review_required",
                    f"Play is installed, but recurring Plays remain off: {error}",
                )
            )
    if (
        "claude" in selected
        and isinstance(tulving_state, dict)
        and tulving_state.get("ready") is True
    ):
        claude_executable = plan_targets.get("claude", {}).get("command")
        tulving_executable = tulving_state.get("executable")
        if isinstance(claude_executable, str) and isinstance(tulving_executable, str):
            steps.append(
                active_progress.call(
                    "Connecting Tulving recall to Claude Code",
                    lambda: converge_claude_tulving_mcp(
                        claude_executable,
                        tulving_executable,
                        runner=runner,
                    ),
                )
            )
    if any(step.status in {"failed", "approval_required"} for step in steps):
        status = "blocked"
    elif any(step.status in {"human_action_required", "review_required"} for step in steps):
        status = "action_required"
    elif any(step.status == "onboarding_required" for step in steps):
        status = "onboarding_required"
    else:
        status = "completed"
    if status == "blocked":
        return rollback_failed_update()
    if status == "completed":
        try:
            removed = prune_play_backups(protect=[run_id])
            steps.append(
                Step(
                    "retain_play_backups",
                    "completed" if removed else "unchanged",
                    (
                        "Retained the newest "
                        f"{BACKUP_RETENTION} verified Play recovery points; pruned "
                        + ", ".join(removed)
                        if removed
                        else f"Play recovery points are within the newest-{BACKUP_RETENTION} retention limit."
                    ),
                    changed=bool(removed),
                    evidence=str(_backup_root()),
                )
            )
        except (BootstrapError, OSError) as error:
            steps.append(
                Step(
                    "retain_play_backups",
                    "review_required",
                    f"Play installed successfully, but old recovery points could not be pruned: {error}",
                    evidence=str(_backup_root()),
                )
            )
            status = "action_required"
    return finish_report(status)


def _finish_report(
    plan: dict[str, Any],
    run_id: str,
    started: str,
    steps: Sequence[Step],
    *,
    status: str,
    runner: Runner,
) -> dict[str, Any]:
    planned_play = plan.get("play", {})
    installed_play_version = (
        planned_play.get("installed_version")
        if isinstance(planned_play, dict)
        else None
    )
    target_play_version = (
        planned_play.get("target_version")
        if isinstance(planned_play, dict)
        else plan.get("play_version")
    )
    replacement_completed = any(
        step.id == "install_play" and step.status == "completed" for step in steps
    )
    active_play_version = (
        target_play_version
        if replacement_completed and status != "rolled_back"
        else installed_play_version
    )
    report = {
        "schema": REPORT_SCHEMA,
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "status": status,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "os": plan.get("os") or _os_snapshot(),
        "selected_harnesses": plan["selected_harnesses"],
        "targets": plan["targets"],
        "play": {
            "before": {"version": installed_play_version},
            "after": {"version": active_play_version},
            "target_version": target_play_version,
            "install_state": (
                planned_play.get("install_state")
                if isinstance(planned_play, dict)
                else None
            ),
            "missing_paths_before": (
                planned_play.get("missing_paths", [])
                if isinstance(planned_play, dict)
                else []
            ),
        },
        "rote": {
            "before": plan["rote"],
            "after": _rote_snapshot(runner, check_update=False),
        },
        "rote_skills": {
            "before": plan["rote_skills"],
            "after": _rote_skills_snapshot(
                [
                    str(item["provider"])
                    for item in plan["rote_skills"]
                    if isinstance(item, dict) and item.get("provider") in ROTE_SKILL_PROVIDERS
                ]
            ),
        },
        "tulving": {
            "requested": plan.get("enable_tulving_requested") is True,
            "before": plan.get("tulving", {}),
            "after": probe_tulving(),
        },
        "steps": [asdict(step) for step in steps],
        "restart": "Restart every selected running harness so it reloads skills and hooks.",
    }
    backup_step = next(
        (
            step
            for step in steps
            if step.id == "backup_play_state"
            and step.status == "completed"
            and isinstance(step.evidence, str)
        ),
        None,
    )
    if backup_step is not None:
        manifest_path = Path(str(backup_step.evidence)).expanduser()
        try:
            manifest = _load_backup_manifest(manifest_path)
            dossier_path = _report_root() / "runs" / f"{run_id}.json"
            restore_executable = _portable_play_path() / "scripts" / "bin" / "play-bootstrap"
            restore_command = (
                f"{shlex.quote(str(restore_executable))} restore --dossier "
                f"{shlex.quote(str(dossier_path))}"
            )
            report["backup"] = {
                "run_id": manifest["run_id"],
                "manifest_path": str(manifest_path),
                "manifest_sha256": _manifest_sha256(manifest_path),
                "has_previous_state": any(
                    entry.get("kind") != "absent" for entry in manifest["entries"]
                ),
                "retention": BACKUP_RETENTION,
                "auto_restored": any(
                    step.id == "rollback_play_state" and step.status == "completed"
                    for step in steps
                ),
                "restore_command": restore_command,
            }
        except (BootstrapError, OSError):
            # The completed backup step remains the durable evidence. Report
            # enrichment must never conceal the install result.
            pass
    json_path, markdown_path = write_report(report)
    return {**report, "report_paths": {"json": str(json_path), "markdown": str(markdown_path)}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "install"):
        command = subparsers.add_parser(name)
        command.add_argument("--top-k", type=int, default=3)
        command.add_argument("--harness", action="append", choices=SUPPORTED_HARNESSES)
        command.add_argument("--json", action="store_true")
    apply_parser = subparsers.choices["apply"]
    apply_parser.add_argument("--approve-remote-installer", action="store_true")
    apply_parser.add_argument("--enable-tulving", action="store_true")
    apply_parser.add_argument("--login-provider", choices=LOGIN_PROVIDERS)
    apply_parser.add_argument("--remote-auth", action="store_true")
    apply_parser.add_argument("--run-id")
    apply_parser.add_argument("--plan-id")
    install_parser = subparsers.choices["install"]
    install_parser.add_argument(
        "--yes",
        action="store_true",
        help="apply the displayed Play plan without its interactive confirmation",
    )
    install_parser.add_argument(
        "--enable-tulving",
        action="store_true",
        help="install, update, or initialize Tulving after Play verification",
    )
    install_parser.add_argument(
        "--approve-remote-installer",
        action="store_true",
        help="approve https://getrote.dev/install for unattended setup",
    )
    install_parser.add_argument(
        "--login-provider",
        choices=LOGIN_PROVIDERS,
        help="complete first-run Rote sign-in with this OAuth provider",
    )
    install_parser.add_argument(
        "--remote-auth",
        action="store_true",
        help="install Rote, then pause for a provision token claimed outside Play",
    )
    install_parser.add_argument(
        "--browser-mode",
        choices=BROWSER_MODES,
        default="auto",
        help="override automatic browser-session detection",
    )
    install_parser.add_argument(
        "--mode",
        choices=("guided", "details"),
        default="guided",
        help="show a concise guided setup or the complete change plan",
    )
    install_parser.add_argument("--run-id")
    backup_parser = subparsers.add_parser(
        "backup", help="list or inspect retained Play recovery points"
    )
    backup_subparsers = backup_parser.add_subparsers(
        dest="backup_command", required=True
    )
    backup_list_parser = backup_subparsers.add_parser("list")
    backup_list_parser.add_argument("--json", action="store_true")
    backup_show_parser = backup_subparsers.add_parser("show")
    backup_show_parser.add_argument("run_id")
    backup_show_parser.add_argument("--json", action="store_true")
    restore_parser = subparsers.add_parser(
        "restore", help="restore Play-owned harness state from a recovery point"
    )
    restore_source = restore_parser.add_mutually_exclusive_group(required=True)
    restore_source.add_argument("--dossier", type=Path)
    restore_source.add_argument("--backup", dest="backup_run_id")
    restore_parser.add_argument(
        "--plan", action="store_true", help="show the immutable restore plan only"
    )
    restore_parser.add_argument(
        "--yes", action="store_true", help="apply the restore without prompting"
    )
    restore_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    progress = _installer_progress()
    try:
        _require_supported_os()
        if args.command == "backup":
            if args.backup_command == "list":
                payload = list_play_backups()
            else:
                payload = _load_backup_manifest(_backup_manifest_path(args.run_id))
        elif args.command == "restore":
            restore_plan = build_restore_plan(
                dossier=args.dossier, backup_run_id=args.backup_run_id
            )
            if args.plan:
                payload = restore_plan
            else:
                if not args.yes:
                    print(_render_restore_plan(restore_plan))
                    if not _confirm(
                        "Restore this Play recovery point?", default=False
                    ):
                        print("Play restore cancelled before any changes were made.")
                        return 0
                payload = restore_play_state(restore_plan)
        elif args.command == "plan":
            payload = progress.call(
                "Checking Play, Rote, and Tulving updates",
                lambda: build_plan(top_k=args.top_k, requested=args.harness),
            )
        elif args.command == "apply":
            source = Path(__file__).resolve().parents[3]
            payload = apply(
                source,
                top_k=args.top_k,
                requested=args.harness,
                approve_remote_installer=args.approve_remote_installer,
                enable_tulving=args.enable_tulving,
                login_provider=args.login_provider,
                remote_auth=args.remote_auth,
                run_id=args.run_id,
                expected_plan_id=args.plan_id,
                progress=progress,
            )
        else:
            source = Path(__file__).resolve().parents[3]
            requested_harnesses = args.harness
            if requested_harnesses is None and not args.yes:
                requested_harnesses = _choose_detected_harnesses(top_k=args.top_k)
                if not requested_harnesses:
                    print("Play installation cancelled before any changes were made.")
                    return 0
            plan = progress.call(
                "Checking Play, Rote, and Tulving updates",
                lambda: build_plan(
                    top_k=args.top_k, requested=requested_harnesses
                ),
            )
            approve_remote_installer = args.approve_remote_installer
            enable_tulving = args.enable_tulving
            login_provider = args.login_provider
            remote_auth = args.remote_auth
            if login_provider is not None and remote_auth:
                raise BootstrapError(
                    "choose either --login-provider or --remote-auth, not both"
                )
            browser_mode = _browser_mode(args.browser_mode)
            renderer = _render_guided_plan if args.mode == "guided" else _render_plan
            print(renderer(plan), file=sys.stderr if args.json else sys.stdout)
            if not args.yes:
                question = (
                    "Install Rote and Play with this setup?"
                    if plan["rote"]["path"] is None
                    else "Set up Play with these apps?"
                )
                if not _confirm(question, default=True):
                    print("Play installation cancelled before any changes were made.")
                    return 0
                if plan["rote"]["path"] is None:
                    approve_remote_installer = True
                if (
                    plan["rote"].get("identity") in {None, "required", "unavailable"}
                    and login_provider is None
                    and not remote_auth
                ):
                    login_method = _choose_login_method(browser_mode)
                    if login_method == "exit":
                        print(
                            "Play setup exited before activation. Rote sign-in is mandatory "
                            "to activate Play. Setup made no changes to Play-owned state."
                        )
                        return 0
                    if login_method == "remote":
                        remote_auth = True
                    else:
                        login_provider = login_method
                tulving = plan.get("tulving", {})
                tulving_update = (
                    tulving.get("update", {}) if isinstance(tulving, dict) else {}
                )
                update_available = (
                    isinstance(tulving_update, dict)
                    and tulving_update.get("status") == "available"
                )
                if not (
                    isinstance(tulving, dict)
                    and tulving.get("ready") is True
                    and not update_available
                ):
                    if update_available and tulving.get("ready") is True:
                        tulving_question = (
                            "Update Tulving to "
                            f"{tulving_update.get('latest')}? Tulving keeps its own release cycle."
                        )
                    elif update_available:
                        tulving_question = (
                            "Update and enable recurring Plays with Tulving? "
                            "Setup also initializes its clock."
                        )
                    else:
                        tulving_question = (
                            "Enable recurring Plays with Tulving? "
                            "Setup installs it only if needed."
                        )
                    enable_tulving = _confirm(
                        tulving_question,
                        default=False,
                    )
            elif (
                plan["rote"].get("identity") in {None, "required", "unavailable"}
                and login_provider is None
                and not remote_auth
                and browser_mode == "headless"
            ):
                remote_auth = True
            payload = apply(
                source,
                top_k=args.top_k,
                requested=requested_harnesses,
                approve_remote_installer=approve_remote_installer,
                enable_tulving=enable_tulving,
                login_provider=login_provider,
                remote_auth=remote_auth,
                run_id=args.run_id,
                expected_plan_id=plan["plan_id"],
                prepared_plan=plan,
                progress=progress,
            )
    except KeyboardInterrupt:
        parser.exit(
            130,
            "\nPlay setup cancelled. Re-run the same command to reuse completed checkpoints.\n",
        )
    except (BootstrapError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"play-bootstrap: {error}\n")
    if args.command == "plan":
        rendered = _render_plan(payload)
    elif args.command == "install":
        rendered = _render_status_card(payload)
    elif args.command == "apply":
        rendered = _markdown(payload)
    elif args.command == "backup" and args.backup_command == "list":
        rendered = _render_backup_catalog(payload)
    elif args.command == "backup":
        rendered = _render_backup_manifest(payload)
    elif payload.get("schema") == RESTORE_PLAN_SCHEMA:
        rendered = _render_restore_plan(payload)
    else:
        rendered = _render_restore_report(payload)
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else rendered)
    return (
        0
        if payload.get("status", "completed")
        in {"completed", "onboarding_required", "action_required"}
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
