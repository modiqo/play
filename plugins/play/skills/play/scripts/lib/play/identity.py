"""Owner-private preference for recovering a Rote registry identity."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from .private_store import PrivateStoreError, atomic_write_json, load_json, locked_store
from .state_home import state_path


IDENTITY_PREFERENCE_SCHEMA = "play.identity-preference/v1"
LOGIN_PROVIDERS = frozenset({"google", "github"})
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def default_identity_preference_path() -> Path:
    return state_path("identity-preference.json")


def last_login_provider(*, path: Path | None = None) -> str | None:
    """Return the last Play-verified OAuth provider, or ``None`` safely."""

    preference_path = path or default_identity_preference_path()
    try:
        payload = load_json(preference_path)
    except (FileNotFoundError, PrivateStoreError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != IDENTITY_PREFERENCE_SCHEMA:
        return None
    provider = payload.get("last_login_provider")
    return provider if provider in LOGIN_PROVIDERS else None


def remember_login_provider(provider: str, *, path: Path | None = None) -> bool:
    """Store one provider hint without retaining identity or credential data."""

    if provider not in LOGIN_PROVIDERS:
        return False
    preference_path = path or default_identity_preference_path()
    payload = {
        "schema": IDENTITY_PREFERENCE_SCHEMA,
        "last_login_provider": provider,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with locked_store(preference_path.parent):
            atomic_write_json(preference_path, payload)
    except PrivateStoreError:
        return False
    return True


def rote_session_status(result: subprocess.CompletedProcess[str]) -> str:
    """Classify Rote's refresh-aware ``whoami --check`` contract."""

    output = "\n".join(
        part for part in (result.stdout, result.stderr) if part
    ).lower()
    if result.returncode == 77 or any(
        marker in output
        for marker in ("not logged in", "authentication required", "login required")
    ):
        return "required"
    if result.returncode == 0:
        return "authenticated"
    return "error"


def _check_session(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _login_visible(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), text=True, check=False, timeout=600)


def recover_rote_session(
    rote: str,
    *,
    check_runner: Runner = _check_session,
    login_runner: Runner = _login_visible,
    preference_path: Path | None = None,
) -> tuple[str, str | None]:
    """Refresh Rote, then reuse the last provider only when login is required."""

    check = check_runner([rote, "whoami", "--check"])
    status = rote_session_status(check)
    if status != "required":
        return status, None
    provider = last_login_provider(path=preference_path)
    if provider is None:
        return "required", None
    login = login_runner([rote, "login", "--provider", provider])
    if login.returncode != 0:
        return "required", provider
    verified = check_runner([rote, "whoami", "--check"])
    verified_status = rote_session_status(verified)
    return ("recovered" if verified_status == "authenticated" else verified_status), provider
