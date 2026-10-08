"""Call the common search Worker using the released Rote login state."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from subprocess import run as run_rote
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit

from .commands import CommandError


PLAY_ROOT = Path(__file__).resolve().parents[3]


REGISTRIES = {
    "https://roteprod.registry.modiqo.ai": "production",
    "https://vovpajqyrnhpzbzpzrny.supabase.co": "production",
    "https://rotestaging.registry.modiqo.ai": "staging",
    "https://cacnimlymbromsrnkaha.supabase.co": "staging",
}
ENDPOINTS = {
    name: f"https://modiqo-play-search-{name}.chetan-9b1.workers.dev/v1/search"
    for name in ("production", "staging")
}

PLAY_ORIGINS = {
    "production": "https://play.modiqo.ai/",
    "staging": "https://play.stg.modiqo.ai/",
    "test": "https://play.test.modiqo.ai/",
}


def _secure_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise CommandError("Invalid custom search endpoint.") from None
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in value)
        or parsed.scheme not in ("https", "http")
        or parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "::1")
        or port == 0
    ):
        raise CommandError("Search endpoints require HTTPS or explicit literal HTTP loopback, without credentials, query, or fragment.")
    return value


def registry_environment(config: dict) -> str:
    url = config.get("url")
    if not isinstance(url, str):
        raise CommandError("Invalid Rote registry URL.")
    if environment := REGISTRIES.get(url):
        return environment
    _secure_endpoint(url)
    if urlsplit(url).hostname not in ("127.0.0.1", "::1"):
        raise CommandError("Owned test registries require a literal loopback registry URL.")
    return "test"


def search_binding(config: dict) -> tuple[str, str, str]:
    environment = registry_environment(config)
    custom = os.environ.get("PLAY_SEARCH_ENDPOINT")
    endpoint = _secure_endpoint(custom) if custom else None
    if environment == "test" and not endpoint:
        raise CommandError("Owned test registries require an explicit search endpoint.")
    return environment, config["url"], endpoint or ENDPOINTS[environment]


def play_origin() -> str:
    return PLAY_ORIGINS[registry_environment(registry_config())]


def require_hosted_cards() -> None:
    if play_origin() == PLAY_ORIGINS["test"]:
        raise CommandError("Public website cards are unsupported for the configured local registry; use native Play inspection through Rote.")

class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def play_version() -> str:
    try:
        return (PLAY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def registry_config() -> dict:
    override = os.environ.get("ROTE_REGISTRY_ENV")
    if override:
        name = {"prod": "production", "stage": "staging"}.get(override, override)
        if name not in ENDPOINTS:
            raise CommandError("Shared search requires a production or staging registry.")
        # Rote's environment override deliberately ignores saved credentials.
        return {"url": next(url for url, environment in REGISTRIES.items() if environment == name)}
    path = Path(os.environ.get("ROTE_HOME", "~/.rote")).expanduser() / "registry/config.json"
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        return {"url": "https://roteprod.registry.modiqo.ai"}
    except (OSError, ValueError):
        raise CommandError("Cannot read the Rote registry configuration.") from None
    if not isinstance(config, dict):
        raise CommandError("Invalid Rote registry configuration.")
    return config


def request_search(query: str, *, public: bool, org: str | None, limit: int, timeout_seconds: float) -> dict:
    if org is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", org):
        raise CommandError("Organization search requires a valid organization handle.")
    if public and org:
        raise CommandError("Organization search requires accessible scope.")
    config = registry_config()
    environment, registry_url, endpoint = search_binding(config)
    headers = {"Content-Type": "application/json", "X-Modiqo-Registry-Environment": environment, "User-Agent": f"modiqo-play/{play_version()}"}
    if not public:
        try:
            identity = run_rote(["rote", "whoami", "--check"], text=True, capture_output=True, check=False, timeout=timeout_seconds)
        except (OSError, subprocess.TimeoutExpired):
            raise CommandError("Cannot verify the Rote login for shared search.") from None
        if identity.returncode:
            raise CommandError("Sign in through Play before searching your Plays and organizations.")
        # whoami refreshes and persists credentials under Rote's own locking rules.
        config = registry_config()
        token = config.get("access_token")
        if search_binding(config) != (environment, registry_url, endpoint) or not isinstance(token, str) or not token:
            raise CommandError("No usable login for this search environment. Sign in through Play.")
        headers["Authorization"] = "Bearer " + token
    body = {"query": query, "limit": limit, "scopes": ["organizations"] if org else ["community"] if public else ["community", "personal", "organizations"]}
    if org:
        body["org"] = org
    request = Request(endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with build_opener(NoRedirects()).open(request, timeout=timeout_seconds) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise CommandError("Shared search response exceeded its size limit.")
        result = json.loads(raw)
    except HTTPError as error:
        error.close()
        raise CommandError(f"Shared search failed (HTTP {error.code}); no fallback or scope change was used.") from None
    except (OSError, URLError, ValueError):
        raise CommandError("Shared search is unavailable or returned invalid JSON; no local fallback was used.") from None
    if not isinstance(result, dict) or result.get("registry") != environment:
        raise CommandError("Shared search returned the wrong registry environment.")
    if os.environ.get("PLAY_SEARCH_ENDPOINT") and result.get("registry_url") != registry_url:
        raise CommandError("Shared search returned the wrong registry URL binding.")
    return result
