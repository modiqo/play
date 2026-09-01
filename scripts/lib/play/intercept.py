"""Blazing-fast, local-only discovery of replayable Plays.

`play-intercept prompt` runs on every UserPromptSubmit. It is local-only and
must stay far under 100ms: action-shaped prompts are compared with an
mtime-keyed index of replayable local Plays and a verified public catalog
cache. A strong match adds one non-blocking suggestion. Everything else
produces no output, so the harness continues normally.

Legacy milestone commands remain accepted as silent no-ops so an older Stop
hook cannot load Play state before the installer removes it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .inbox_cache import read_cache as read_inbox_cache
from .normalize import token_is_covered
from .private_store import atomic_write_json, load_json
from .state_home import state_path


INDEX_SCHEMA = "play.intercept-index/v1"
FRONTMATTER_BYTES = 4096
MIN_PROMPT_CHARS = 8
_REPLAYABLE = re.compile(r"^#![^\n]*\brote\s+play\s+run\b", re.MULTILINE)

_BARE_HELLO_REQUEST = re.compile(
    r"^(?:please\s+)?run\s+(?:the\s+)?hello(?:\s+play)?[.!]?$",
    re.IGNORECASE,
)
_ACTION_REQUEST = re.compile(
    r"^(?:(?:please|kindly)\s+)?(?:(?:can|could|would)\s+you(?:\s+(?:now|please)){0,2}\s+)?"
    r"(?:(?:help\s+me|help|(?:let'?s|i\s+want\s+you\s+to))\s+)?"
    r"(?:use|run|execute|create|make|write|edit|change|update|fix|implement|"
    r"refactor|review|test|verify|investigate|diagnose|build|configure|install|"
    r"delete|set|add|remove|enable|disable|open|close|commit|push|pull|merge|"
    r"trigger|cancel|retry|rerun|retrieve|fetch|get|find|collect|download|"
    r"export|list|summarize|check|monitor|calculate|compare|deploy|publish|"
    r"release|ship)\b",
    re.IGNORECASE,
)
_DISCUSSION_REQUEST = re.compile(
    r"^(?:why|how|what|when|where|who|should\s+(?:we|i)|can\s+(?:we|i)|"
    r"could\s+(?:we|i)|would\s+(?:we|i))\b",
    re.IGNORECASE,
)
_REQUEST_PREFIX = re.compile(
    r"^(?:(?:please|kindly)\s+)?(?:"
    r"(?:can|could|would)\s+you(?:\s+(?:now|please)){0,2}\b|"
    r"help(?:\s+me)?\b|let'?s\b|i\s+want\s+you\s+to\b)",
    re.IGNORECASE,
)
_PREFIXED_DISCUSSION = re.compile(
    r"^(?:(?:please|kindly)\s+)?(?:can|could|would)\s+you"
    r"(?:\s+(?:now|please)){0,2}\s+"
    r"(?:explain|discuss|describe|clarify|tell\s+me)\b",
    re.IGNORECASE,
)
_NAME = re.compile(r"^\s*\*?\s*name:\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*$", re.MULTILINE)
_DESCRIPTION = re.compile(r"^\s*\*?\s*description:\s*(.+)$", re.MULTILINE)
_TAG = re.compile(r"^\s*\*?\s*-\s*([a-z0-9][a-z0-9_-]*)\s*$", re.MULTILINE)
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are at be by can could do for from get has have how i in is it me my of on or "
    "only play plays please rote run runs should skill status that the this to us we what when "
    "with you your".split()
)


def _flows_root() -> Path:
    override = os.environ.get("PLAY_INTERCEPT_FLOWS_ROOT")
    return Path(override) if override else Path.home() / ".rote" / "flows"


def _index_path() -> Path:
    override = os.environ.get("PLAY_INTERCEPT_INDEX_PATH")
    return Path(override) if override else state_path("intercept-index.json")


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(text.casefold())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _flow_dirs(root: Path) -> list[tuple[str, Path]]:
    """Yield (reference, main.ts path) for local flows and pulled owner/name flows."""

    found: list[tuple[str, Path]] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.is_dir():
            continue
        main = entry / "main.ts"
        if main.is_file():
            found.append((entry.name, main))
            continue
        try:
            children = sorted(entry.iterdir())
        except OSError:
            continue
        for child in children:
            nested = child / "main.ts"
            if child.is_dir() and nested.is_file():
                found.append((f"{entry.name}/{child.name}", nested))
    return found


def _signature(flows: list[tuple[str, Path]]) -> str:
    parts = []
    for reference, main in flows:
        try:
            parts.append(f"{reference}:{int(main.stat().st_mtime)}")
        except OSError:
            continue
    return "|".join(parts)


def _parse_entry(reference: str, main: Path) -> dict[str, Any] | None:
    try:
        header = main.read_text(errors="ignore")[:FRONTMATTER_BYTES]
    except OSError:
        return None
    if _REPLAYABLE.search(header) is None:
        return None
    name_match = _NAME.search(header)
    description_match = _DESCRIPTION.search(header)
    name = name_match.group(1) if name_match else reference.rsplit("/", 1)[-1]
    description = (description_match.group(1).strip() if description_match else "")[:240]
    tags = _TAG.findall(header)[:12]
    return {
        "reference": reference,
        "name": name,
        "description": description,
        "tags": tags,
        "name_tokens": sorted(_tokens(name.replace("-", " "))),
        "text_tokens": sorted(_tokens(" ".join([description, *tags]))),
    }


def load_index(root: Path | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """Return the play index, rebuilding only when the flows tree changed."""

    resolved_root = root or _flows_root()
    resolved_path = path or _index_path()
    flows = _flow_dirs(resolved_root)
    signature = _signature(flows)
    try:
        cached = load_json(resolved_path)
    except (OSError, ValueError):
        cached = None
    if (
        isinstance(cached, Mapping)
        and cached.get("schema") == INDEX_SCHEMA
        and cached.get("signature") == signature
        and isinstance(cached.get("entries"), list)
    ):
        return list(cached["entries"])
    entries = [
        entry
        for reference, main in flows
        if (entry := _parse_entry(reference, main)) is not None
    ]
    try:
        atomic_write_json(
            resolved_path,
            {"schema": INDEX_SCHEMA, "signature": signature, "entries": entries},
        )
    except OSError:
        pass
    return entries


def _hub_entries(local_names: set[str]) -> list[dict[str, Any]]:
    """Authorized hub Plays from the inbox catalog cache — zero network."""

    cache = read_inbox_cache()
    if cache is None or cache.get("catalog_complete") is not True:
        return []
    catalog = cache.get("public_catalog")
    if not isinstance(catalog, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in catalog:
        if not isinstance(item, Mapping):
            continue
        reference = item.get("reference")
        name = item.get("name")
        if (
            not isinstance(reference, str)
            or not isinstance(name, str)
            or item.get("visibility") != "public"
            or name in local_names
        ):
            continue
        description = str(item.get("description") or "")[:240]
        labels = _string_values(item.get("labels"))
        tags = _string_values(item.get("tags"))
        adapters = _string_values(item.get("adapters"))
        entries.append(
            {
                "reference": reference,
                "name": name,
                "description": description,
                "scope": "hub",
                "catalog_tier": item.get("catalog_tier"),
                "name_tokens": sorted(_tokens(name.replace("-", " "))),
                "text_tokens": sorted(
                    _tokens(" ".join([description, *labels, *tags, *adapters]))
                ),
                "labels": labels,
                "tags": tags,
                "adapters": adapters,
            }
        )
    return entries


def _ranked_match(
    prompt: str, entries: list[dict[str, Any]]
) -> tuple[dict[str, Any], int, int] | None:
    """Return the best entry with its weighted score and name-token hits."""

    prompt_tokens = _tokens(prompt)
    if not prompt_tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    best_name_hits = 0
    for entry in entries:
        name_tokens = set(entry.get("name_tokens", []))
        name_hits = sum(
            token_is_covered(name_token, prompt_tokens)
            for name_token in name_tokens
        )
        text_hits = len(prompt_tokens & set(entry.get("text_tokens", [])))
        score = name_hits * 3 + text_hits
        if score > best_score:
            best, best_score, best_name_hits = entry, score, name_hits
    if best is not None:
        return best, best_score, best_name_hits
    return None


def best_match(prompt: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a high-confidence match backed by two Play-name tokens."""

    ranked = _ranked_match(prompt, entries)
    if ranked is None:
        return None
    best, score, name_hits = ranked
    if score >= 4 and name_hits >= 2:
        return best
    return None


def is_bare_hello_request(prompt: str) -> bool:
    """Keep an unprefixed Hello request on the normal agent route."""

    return _BARE_HELLO_REQUEST.fullmatch(prompt.strip()) is not None


def is_action_request(prompt: str) -> bool:
    """Keep catalog token overlap from surfacing Plays for discussions."""

    stripped = prompt.strip()
    return (
        _DISCUSSION_REQUEST.match(stripped) is None
        and _ACTION_REQUEST.match(stripped) is not None
    )


def _is_match_backed_request(prompt: str) -> bool:
    """Allow a strong catalog match to recover a misspelled action verb."""

    stripped = prompt.strip()
    return (
        _DISCUSSION_REQUEST.match(stripped) is None
        and _PREFIXED_DISCUSSION.match(stripped) is None
        and _REQUEST_PREFIX.match(stripped) is not None
    )


def intercept_prompt(
    prompt: str,
    *,
    session_id: str | None = None,
    project_path: str | None = None,
) -> str | None:
    """Return the one context line to inject, or None for silence."""

    stripped = prompt.strip()
    if is_bare_hello_request(stripped):
        return None
    if (
        len(stripped) < MIN_PROMPT_CHARS
        or stripped.startswith(("$play", "/play", "!", "/"))
    ):
        return None
    action_request = is_action_request(stripped)
    if not action_request and not _is_match_backed_request(stripped):
        return None
    entries = load_index()
    unpublished_names = {
        entry["name"]
        for entry in entries
        if isinstance(entry.get("name"), str)
        and "/" not in str(entry.get("reference") or "")
    }
    hub_entries = _hub_entries(unpublished_names)
    # The refreshed authorized catalog is the canonical publication namespace.
    # Do not let a stale locally pulled copy under a retired organization shadow
    # the current hub reference merely because both share the same Play name.
    hub_names = {entry["name"] for entry in hub_entries}
    entries = [
        *[entry for entry in entries if entry.get("name") not in hub_names],
        *hub_entries,
    ]
    match = best_match(stripped, entries)
    if match is not None:
        description = match.get("description") or "a saved Play"
        return (
            f"Play suggestion: high-confidence match `{match['reference']}` — {description} "
            "Show one quiet, non-blocking line: "
            f"\"Play found: `{match['reference']}` — explicitly invoke Play with "
            f"`{match['reference']}` to inspect it.\" Do not enter the Play state "
            "machine, load Play or Rote state, pause, or change the original request."
        )
    return None


def milestone_nudge(session_id: str | None) -> str | None:
    """Return an explicit workflow's exploration pulse or achievement nudge."""

    from .journal import claim_exploration_pulse, render_pulse
    from .milestones import claim_nudge

    pulse = claim_exploration_pulse(session_id=session_id)
    return render_pulse(pulse) if pulse is not None else claim_nudge(session_id=session_id)


def settle_nudge(session_id: str | None) -> str | None:
    """Compatibility alias for hooks installed before milestone nudges."""

    return milestone_nudge(session_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-intercept", description=__doc__)
    parser.add_argument(
        "command", choices=["prompt", "milestone-nudge", "settle-nudge"]
    )
    arguments = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if arguments.command == "prompt":
        prompt = payload.get("prompt")
        session_id = payload.get("session_id")
        project_path = payload.get("cwd") or payload.get("workspace_root")
        line = (
            intercept_prompt(
                prompt,
                session_id=session_id if isinstance(session_id, str) else None,
                project_path=project_path if isinstance(project_path, str) else None,
            )
            if isinstance(prompt, str)
            else None
        )
        if line:
            print(
                json.dumps(
                    {
                        "suppressOutput": True,
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": line,
                        },
                    }
                )
            )
        return 0

    # Older installers registered these commands on Stop. Keep the CLI names
    # valid but inert so updating a source-linked Play is safe before the next
    # installer convergence removes the stale hook entries.
    return 0
