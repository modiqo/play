"""Blazing-fast structural interception for the two sidekick moments.

`play-intercept prompt` runs on every UserPromptSubmit. It is local-only and
must stay far under 100ms: action-shaped prompts pass through trusted user and
project routing policy, then an mtime-keyed index of saved Plays (built from
`~/.rote/flows` frontmatter) is matched lexically. A direct prefix or validated
route injects a whole-turn Play-and-Rote bypass contract before catalog access;
discussion or scoped silence produces nothing. On a specific hit it injects one
context line naming the Play; on an outcome-shaped prompt with no local hit it
injects, at most once per cooldown window, one line advising the agent to search
preexisting Plays through the play skill.

`play-intercept milestone-nudge` runs on Stop. It claims at most one internal
achievement event and teaches the next useful Play behavior. Capture and settle
handles remain internal to their typed workflow and never leak through Stop.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .inbox_cache import read_cache as read_inbox_cache
from .milestones import claim_nudge
from .normalize import token_is_covered
from .private_store import atomic_write_json, load_json
from .routing import is_routing_management_request, matching_direct_route
from .state_home import state_path
from .sidekick import coarse_task_class, preference_policy


INDEX_SCHEMA = "play.intercept-index/v1"
STATE_SCHEMA = "play.intercept-state/v1"
ADVICE_COOLDOWN_SECONDS = 3600
FRONTMATTER_BYTES = 4096
MIN_PROMPT_CHARS = 8

_FAST_OUTCOME = re.compile(
    r"^(?:(?:please|kindly)\s+)?(?:(?:can|could|would)\s+you(?:\s+(?:now|please)){0,2}\s+)?"
    r"(?:(?:help\s+me|help)\s+)?"
    r"(?:retrieve|fetch|get|find|collect|download|export|list|summarize|check|"
    r"monitor|calculate|compare|deploy|publish|ship)\b",
    re.IGNORECASE,
)
_DIRECT_REQUEST = re.compile(
    r"^(?:direct|without\s+play)\s*:\s*\S",
    re.IGNORECASE,
)
_CHEAT_SHEET_REQUEST = re.compile(
    r"^(?:\$play|/play|play)\s+cheat(?:[\s-]?sheet)[.!]?$",
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
    "please should status that the this to us we what when with you your".split()
)


def _flows_root() -> Path:
    override = os.environ.get("PLAY_INTERCEPT_FLOWS_ROOT")
    return Path(override) if override else Path.home() / ".rote" / "flows"


def _index_path() -> Path:
    override = os.environ.get("PLAY_INTERCEPT_INDEX_PATH")
    return Path(override) if override else state_path("intercept-index.json")


def _state_path() -> Path:
    override = os.environ.get("PLAY_INTERCEPT_STATE_PATH")
    return Path(override) if override else state_path("intercept-state.json")


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
        "name_tokens": sorted(_tokens(name.replace("-", " ")) | _tokens(" ".join(tags))),
        "text_tokens": sorted(_tokens(description)),
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
    if cache is None:
        return []
    catalog = cache.get("catalog")
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
                "name_tokens": sorted(
                    _tokens(name.replace("-", " "))
                    | _tokens(" ".join([*labels, *tags, *adapters]))
                ),
                "text_tokens": sorted(_tokens(description)),
                "labels": labels,
                "tags": tags,
                "adapters": adapters,
            }
        )
    return entries


def best_match(prompt: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Score prompt tokens against name/tag (weight 3) and description (weight 1)."""

    prompt_tokens = _tokens(prompt)
    if not prompt_tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for entry in entries:
        name_tokens = set(entry.get("name_tokens", []))
        name_hits = sum(
            token_is_covered(name_token, prompt_tokens)
            for name_token in name_tokens
        )
        text_hits = len(prompt_tokens & set(entry.get("text_tokens", [])))
        score = name_hits * 3 + text_hits
        if score > best_score:
            best, best_score = entry, score
    if best is not None and best_score >= 4 and sum(
        token_is_covered(name_token, prompt_tokens)
        for name_token in set(best.get("name_tokens", []))
    ) >= 2:
        return best
    return None


def is_direct_request(prompt: str) -> bool:
    """Return whether the user selected the explicit one-turn Play bypass."""

    return _DIRECT_REQUEST.match(prompt.strip()) is not None


def _direct_bypass_context(route: Mapping[str, Any] | None = None) -> str:
    """Stamp the complete inference turn with an explicit negative route."""

    if route is None:
        scope = "The user explicitly selected the one-turn direct prefix."
        path = "Use harness-native tools or the relevant vendor API/CLI directly."
    else:
        providers = ", ".join(route["providers"]) or "none"
        tools = ", ".join(route["tools"]) or "none"
        executors = ", ".join(route["executors"])
        scope = (
            f"Validated direct route `{route['id']}` matched "
            f"(providers: {providers}; tools: {tools}; executors: {executors})."
        )
        path = (
            "Use harness-native tools or only the matched vendor API/CLI path "
            "allowed by that route."
        )
    return (
        "Play direct bypass: "
        f"{scope} For this entire user turn, bypass both Play and Rote orchestration. "
        "Do not invoke Play or Rote skills, CLIs, runtimes, searches, adapters, "
        "workspaces, capture, or follow-up routing during any inference, delegation, "
        f"retry, or tool loop. {path} Normal harness permissions, authentication, "
        "tool approvals, and safety checks still apply."
    )


def is_cheat_sheet_request(prompt: str) -> bool:
    """Return whether the prompt selected Play's deterministic help surface."""

    return _CHEAT_SHEET_REQUEST.match(prompt.strip()) is not None


def is_action_request(prompt: str) -> bool:
    """Keep catalog token overlap from activating Play for discussions."""

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


def _silenced(
    prompt: str,
    *,
    session_id: str | None = None,
    project_path: str | None = None,
) -> bool:
    task_class = coarse_task_class(prompt)
    return (
        preference_policy(
            task_class,
            session_id=session_id,
            project_path=project_path,
        )
        == "silent"
    )


def _advice_recently_given(state_path: Path) -> bool:
    try:
        state = load_json(state_path)
    except (OSError, ValueError):
        return False
    if not isinstance(state, Mapping) or state.get("schema") != STATE_SCHEMA:
        return False
    last = state.get("advice_at_epoch")
    return isinstance(last, (int, float)) and time.time() - last < ADVICE_COOLDOWN_SECONDS


def _record(state_path: Path, **fields: Any) -> None:
    try:
        state = load_json(state_path)
    except (OSError, ValueError):
        state = None
    merged = dict(state) if isinstance(state, Mapping) else {}
    merged.update({"schema": STATE_SCHEMA, **fields})
    try:
        atomic_write_json(state_path, merged)
    except OSError:
        pass


def intercept_prompt(
    prompt: str,
    *,
    session_id: str | None = None,
    project_path: str | None = None,
) -> str | None:
    """Return the one context line to inject, or None for silence."""

    stripped = prompt.strip()
    if is_cheat_sheet_request(stripped):
        return (
            "Play: explicit cheat-sheet request — use the play skill's bundled "
            "`scripts/bin/play-cheat-sheet`, present its Markdown verbatim, and do not "
            "enter the Play state machine."
        )
    if is_routing_management_request(stripped):
        return (
            "Play: explicit routing-policy management request — use the play skill's "
            "pre-machine routing-management path with the unchanged prompt. Default an "
            "unqualified scope to this repository; do not search for or run a saved Play."
        )
    if is_direct_request(stripped):
        return _direct_bypass_context()
    if (
        len(stripped) < MIN_PROMPT_CHARS
        or stripped.startswith(("$play", "/play", "!", "/"))
    ):
        return None
    action_request = is_action_request(stripped)
    if not action_request and not _is_match_backed_request(stripped):
        return None
    if _silenced(
        stripped,
        session_id=session_id,
        project_path=project_path,
    ):
        return None
    direct_route = matching_direct_route(stripped, project_path=project_path)
    if direct_route is not None:
        return _direct_bypass_context(direct_route)
    entries = load_index()
    hub_entries = _hub_entries(set())
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
        if match.get("scope") == "hub":
            return (
                f"Play: Play `{match['reference']}` is available in your hub — {description} "
                "Run it through the play skill: it inspects first, shows the Play card, and "
                "asks approval before running — never pull plays or adapters manually."
            )
        return (
            f"Play: saved Play `{match['reference']}` looks relevant — {description} "
            "Run it through the play skill: it inspects first and asks approval before "
            "running — never decompose it into manual pull or adapter commands."
        )
    if action_request and _FAST_OUTCOME.match(stripped) and entries is not None:
        state_path = _state_path()
        if _advice_recently_given(state_path):
            return None
        _record(state_path, advice_at_epoch=time.time())
        return (
            "Play: this looks like a repeatable outcome — have the play skill search "
            "preexisting saved Plays (local and authorized hubs) before doing it manually."
        )
    return None


def milestone_nudge(session_id: str | None) -> str | None:
    """Return one event-backed achievement nudge, or stay completely silent."""

    return claim_nudge(session_id=session_id)


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

    line = milestone_nudge(payload.get("session_id"))
    if line:
        print(json.dumps({"systemMessage": line, "suppressOutput": True}))
    return 0
