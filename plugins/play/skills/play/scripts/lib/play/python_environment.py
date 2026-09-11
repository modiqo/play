"""Stdlib-only contract for Play's pinned Python environment.

Every Play launcher runs under whatever ``python3`` the harness found first. When
that interpreter lacks the pinned runtime packages, the launcher re-enters itself
through ``uv run`` against the installed skill root. ``uv.lock`` pins every package
to pypi.org, so a network that enforces a private package index needs that index
handed to uv before any download starts. This module resolves that index once,
explains a failed bootstrap in terms of the index that was used, and keeps the
module probe, the sync command, and the failure text identical across the
launchers, the installer, and the preflight.

It must stay importable without any third-party package.
"""

from __future__ import annotations

import configparser
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

RUNTIME_MODULES: tuple[str, ...] = ("ast_grep_py", "jsonschema", "statemachine", "yaml")
RUNTIME_REQUIREMENTS: tuple[str, ...] = (
    "ast-grep-py>=0.39,<1",
    "jsonschema>=4.23,<5",
    "python-statemachine[yaml]>=3.2,<3.3",
    "PyYAML>=6,<7",
)
DEFAULT_INDEX_URL = "https://pypi.org/simple"
INDEX_OVERRIDE_VARIABLE = "PLAY_PYTHON_INDEX_URL"
BOOTSTRAP_GUARD_VARIABLE = "PLAY_UV_BOOTSTRAPPED"
INSTALL_MARKER = ".play-install.json"

_UV_INDEX_VARIABLES = ("UV_DEFAULT_INDEX", "UV_INDEX_URL")
_LOCK_REGISTRY = re.compile(r'registry\s*=\s*"([^"]+)"')
_INDEX_FAILURE_MARKERS = (
    "failed to fetch",
    "request failed",
    "error sending request",
    "pypi.org",
    "pythonhosted.org",
    "dns error",
    "connection refused",
    "connect timed out",
    "timed out",
    "certificate",
    "tls",
    "proxy",
    "403 forbidden",
    "407 proxy",
    "no solution found",
    "not found in the package registry",
)


class PackageIndexError(ValueError):
    """A configured package index URL cannot be used."""


@dataclass(frozen=True)
class PackageIndex:
    """The simple-index URL uv downloads from and where that choice came from."""

    url: str
    source: str

    @property
    def overrides_default(self) -> bool:
        return _normalize(self.url) != _normalize(DEFAULT_INDEX_URL)

    @property
    def uv_native(self) -> bool:
        return self.source in _UV_INDEX_VARIABLES

    def describe(self) -> str:
        if self.source == "default":
            return f"{self.url} (uv default)"
        return f"{self.url} (from {self.source})"


def _normalize(url: str) -> str:
    return url.strip().rstrip("/").lower()


def validate_index_url(url: str, *, source: str) -> str:
    """Accept only an absolute http(s) simple-index URL without whitespace."""

    candidate = url.strip()
    if not candidate:
        raise PackageIndexError(f"{source} is empty")
    if any(character.isspace() for character in candidate):
        raise PackageIndexError(f"{source} must not contain whitespace: {candidate!r}")
    if not re.match(r"^https?://[^/]+", candidate):
        raise PackageIndexError(
            f"{source} must be an absolute http(s) simple-index URL, got {candidate!r}"
        )
    return candidate


def missing_runtime_modules(
    find_spec: Callable[[str], object | None] | None = None,
) -> list[str]:
    """Return every pinned runtime module the current interpreter cannot import."""

    probe = importlib.util.find_spec if find_spec is None else find_spec
    missing: list[str] = []
    for name in RUNTIME_MODULES:
        try:
            present = probe(name) is not None
        except (ImportError, ValueError):
            present = False
        if not present:
            missing.append(name)
    return missing


def _home(environ: Mapping[str, str]) -> Path:
    override = environ.get("HOME")
    return Path(override).expanduser() if override else Path.home()


def pip_config_paths(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Return pip's configuration files in pip's own precedence order, most specific first."""

    env = os.environ if environ is None else environ
    explicit = env.get("PIP_CONFIG_FILE")
    if explicit:
        return (Path(explicit).expanduser(),)
    home = _home(env)
    paths: list[Path] = []
    config_home = env.get("XDG_CONFIG_HOME")
    paths.append(
        (Path(config_home).expanduser() if config_home else home / ".config") / "pip" / "pip.conf"
    )
    if sys.platform == "darwin":
        paths.append(home / "Library" / "Application Support" / "pip" / "pip.conf")
    paths.append(home / ".pip" / "pip.conf")
    paths.append(Path("/etc/pip.conf"))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def pip_config_index(environ: Mapping[str, str] | None = None) -> PackageIndex | None:
    """Return the ``[global] index-url`` pip is configured with, if any file declares one."""

    for path in pip_config_paths(environ):
        if not path.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            continue
        for section in ("global", "install"):
            if parser.has_option(section, "index-url"):
                value = parser.get(section, "index-url").strip()
                if value:
                    return PackageIndex(value, str(path))
    return None


def recorded_package_index(root: Path) -> PackageIndex | None:
    """Return the index the installer recorded in the portable install marker."""

    marker = root / INSTALL_MARKER
    if not marker.is_file():
        return None
    import json

    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    recorded = payload.get("python_index") if isinstance(payload, dict) else None
    if not isinstance(recorded, dict):
        return None
    url = recorded.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    return PackageIndex(url.strip(), f"{INSTALL_MARKER} ({recorded.get('source') or 'recorded'})")


def resolve_package_index(
    root: Path, environ: Mapping[str, str] | None = None
) -> PackageIndex:
    """Pick the simple index uv must download from, most explicit source first.

    Order: ``PLAY_PYTHON_INDEX_URL``, uv's own ``UV_DEFAULT_INDEX`` or ``UV_INDEX_URL``,
    the index recorded by the installer, ``PIP_INDEX_URL``, pip's configuration
    files, then pypi.org.
    """

    env = os.environ if environ is None else environ
    explicit = env.get(INDEX_OVERRIDE_VARIABLE)
    if explicit is not None and explicit.strip():
        return PackageIndex(
            validate_index_url(explicit, source=INDEX_OVERRIDE_VARIABLE),
            INDEX_OVERRIDE_VARIABLE,
        )
    for variable in _UV_INDEX_VARIABLES:
        value = env.get(variable)
        if value is not None and value.strip():
            return PackageIndex(value.strip(), variable)
    recorded = recorded_package_index(root)
    if recorded is not None:
        return recorded
    pip_variable = env.get("PIP_INDEX_URL")
    if pip_variable is not None and pip_variable.strip():
        return PackageIndex(pip_variable.strip(), "PIP_INDEX_URL")
    configured = pip_config_index(env)
    if configured is not None:
        return configured
    return PackageIndex(DEFAULT_INDEX_URL, "default")


def lock_indexes(root: Path) -> tuple[str, ...]:
    """Return every registry URL ``uv.lock`` pins packages to, in first-seen order."""

    lock = root / "uv.lock"
    try:
        text = lock.read_text(encoding="utf-8")
    except OSError:
        return ()
    seen: list[str] = []
    for match in _LOCK_REGISTRY.finditer(text):
        url = match.group(1)
        if url not in seen:
            seen.append(url)
    return tuple(seen)


def lock_matches_index(root: Path, index: PackageIndex) -> bool:
    """Return whether every lock registry is the configured index, so ``--locked`` can hold."""

    pinned = lock_indexes(root)
    if not pinned:
        return True
    return all(_normalize(url) == _normalize(index.url) for url in pinned)


def uv_environment(
    environ: Mapping[str, str], index: PackageIndex
) -> dict[str, str]:
    """Copy the environment and hand uv the resolved index when uv does not already know it."""

    env = dict(environ)
    if index.overrides_default and not index.uv_native:
        env["UV_DEFAULT_INDEX"] = index.url
    return env


def uv_sync_command(uv: str, root: Path, index: PackageIndex) -> list[str]:
    """Build the installer's sync command; ``--locked`` only when the lock and index agree."""

    command = [uv, "sync"]
    if lock_matches_index(root, index):
        command.append("--locked")
    command.extend(["--no-dev", "--inexact", "--project", str(root)])
    return command


def uv_run_command(uv: str, root: Path, script: Path, argv: Sequence[str]) -> list[str]:
    """Build the launcher re-entry command for one bundled Play entrypoint."""

    return [uv, "run", "--no-dev", "--project", str(root), str(script), *argv]


def pip_install_command(index: PackageIndex) -> str:
    """Return the one-line manual fallback that installs the pinned runtime packages."""

    parts = ["python3 -m pip install"]
    if index.overrides_default:
        parts.append(f"--index-url {index.url}")
    parts.extend(f'"{requirement}"' for requirement in RUNTIME_REQUIREMENTS)
    return " ".join(parts)


def looks_like_index_failure(output: str) -> bool:
    """Return whether uv's output reads as a download or index problem, not a Play bug."""

    lowered = output.lower()
    return any(marker in lowered for marker in _INDEX_FAILURE_MARKERS)


def explain_bootstrap_failure(root: Path, index: PackageIndex, *, tool: str) -> str:
    """Explain a failed dependency download in terms of the index uv actually used."""

    pinned = lock_indexes(root)
    lines = [
        f"{tool}: Play could not download its pinned Python packages.",
        f"  Package index used: {index.describe()}",
    ]
    if pinned and not lock_matches_index(root, index):
        lines.append(
            "  uv.lock pins " + ", ".join(pinned) + "; uv re-resolved against the index above."
        )
    elif pinned:
        lines.append("  uv.lock pins " + ", ".join(pinned) + ".")
    if not index.overrides_default:
        lines.append(
            "  If this network enforces a private package index, set "
            f"{INDEX_OVERRIDE_VARIABLE}=<your simple-index URL> (PIP_INDEX_URL and pip.conf "
            "are honored too) and rerun the Play installer."
        )
    else:
        lines.append(
            f"  Confirm that index serves the pinned packages, or point {INDEX_OVERRIDE_VARIABLE} "
            "at one that does, then rerun the Play installer."
        )
    lines.append(
        "  Or install the pinned packages into the interpreter that runs Play yourself:"
    )
    lines.append(f"    {pip_install_command(index)}")
    return "\n".join(lines)


def missing_uv_message(tool: str, missing: Sequence[str], index: PackageIndex) -> str:
    """Explain a launcher that has neither uv nor the pinned packages."""

    return (
        f"{tool} requires uv or the pinned Play Python environment "
        f"(missing: {', '.join(missing)}).\n"
        "  Install uv from https://docs.astral.sh/uv/ and rerun, or install the packages yourself:\n"
        f"    {pip_install_command(index)}"
    )


def record_package_index(root: Path, index: PackageIndex) -> bool:
    """Persist a non-default index in the portable install marker for launcher reuse.

    Harness hook processes often run with a stripped environment; the marker lets
    them reuse the index the installer resolved. Returns whether the marker changed.
    """

    marker = root / INSTALL_MARKER
    if not marker.is_file():
        return False
    import json

    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    desired = (
        {"url": index.url, "source": index.source} if index.overrides_default else None
    )
    if payload.get("python_index") == desired or (
        desired is None and "python_index" not in payload
    ):
        return False
    if desired is None:
        payload.pop("python_index", None)
    else:
        payload["python_index"] = desired
    temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    os.replace(temporary, marker)
    return True


def ensure_runtime(
    tool: str,
    root: Path,
    script: Path,
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    find_spec: Callable[[str], object | None] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    execve: Callable[..., Any] = os.execve,
    stderr=None,
    advisory: bool = False,
    extra_environment: Mapping[str, str] | None = None,
) -> None:
    """Return when the pinned runtime is importable; otherwise re-enter through uv or exit.

    A launcher calls this before importing any Play module that needs third-party
    packages. When the project environment already exists the launcher replaces
    itself with ``uv run`` so streaming stdin and stdout are untouched. Before the
    environment exists, uv's first materialization runs as a child so a failed
    download can be explained in terms of the package index that was used.

    ``advisory`` launchers keep running without uv so their own import fallback
    can degrade gracefully; ``extra_environment`` entries are added with
    ``setdefault`` only to the uv re-entry environment.
    """

    env_in = os.environ if environ is None else environ
    err = sys.stderr if stderr is None else stderr
    missing = missing_runtime_modules(find_spec)
    if not missing:
        return
    index = resolve_package_index(root, env_in)
    if env_in.get(BOOTSTRAP_GUARD_VARIABLE) == "1":
        raise SystemExit(
            f"{tool}: the Play Python environment still lacks {', '.join(missing)} after uv "
            f"bootstrapped it from {index.describe()}.\n    {pip_install_command(index)}"
        )
    uv = which("uv")
    if uv is None:
        if advisory:
            return
        raise SystemExit(missing_uv_message(tool, missing, index))
    env = uv_environment(env_in, index)
    env[BOOTSTRAP_GUARD_VARIABLE] = "1"
    for key, value in (extra_environment or {}).items():
        env.setdefault(key, value)
    command = uv_run_command(uv, root, script, argv)
    if (root / ".venv").is_dir():
        execve(uv, command, env)
        return
    result = run(command, env=env, stderr=subprocess.PIPE, text=True, check=False)
    captured = result.stderr or ""
    if captured:
        err.write(captured)
        if not captured.endswith("\n"):
            err.write("\n")
    if result.returncode != 0 and looks_like_index_failure(captured):
        err.write(explain_bootstrap_failure(root, index, tool=tool) + "\n")
    err.flush()
    raise SystemExit(result.returncode)
