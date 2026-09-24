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

from .commands import CommandError


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


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
    environment = REGISTRIES.get(str(config.get("url", "")))
    if environment is None:
        raise CommandError("Shared search requires a production or staging registry.")
    headers = {"Content-Type": "application/json", "X-Modiqo-Registry-Environment": environment, "User-Agent": "modiqo-play/0.4.100"}
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
        if REGISTRIES.get(str(config.get("url", ""))) != environment or not isinstance(token, str) or not token:
            raise CommandError("No usable login for this search environment. Sign in through Play.")
        headers["Authorization"] = "Bearer " + token
    body = {"query": query, "limit": limit, "scopes": ["organizations"] if org else ["community"] if public else ["community", "personal", "organizations"]}
    if org:
        body["org"] = org
    request = Request(ENDPOINTS[environment], data=json.dumps(body).encode(), headers=headers, method="POST")
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
    return result
