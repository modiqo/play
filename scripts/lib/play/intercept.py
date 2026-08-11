"""Blazing-fast structural interception for the two sidekick moments.

`play-intercept prompt` runs on every UserPromptSubmit. It is local-only and
must stay far under 100ms: an mtime-keyed index of saved Plays (built from
`~/.rote/flows` frontmatter) is matched lexically against the prompt. On a
specific hit it injects one context line naming the Play; on an outcome-shaped
prompt with no local hit it injects, at most once per cooldown window, one line
advising the agent to search preexisting Plays through the play skill. On
everything else: silence, zero tokens. The scoped preference ledger applies —
a silenced task class produces nothing.

`play-intercept settle-nudge` runs on Stop. If a save hook armed this session
is still unsettled, it shows the user one reminder line, once per hook.
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

from .private_store import atomic_write_json, load_json
from .sidekick import coarse_task_class, latest_hook, load_ledger


INDEX_SCHEMA = "play.intercept-index/v1"
STATE_SCHEMA = "play.intercept-state/v1"
ADVICE_COOLDOWN_SECONDS = 3600
FRONTMATTER_BYTES = 4096
MIN_PROMPT_CHARS = 8

_FAST_OUTCOME = re.compile(
    r"^(?:(?:please|kindly)\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"(?:(?:help\s+me|help)\s+)?"
    r"(?:retrieve|fetch|get|find|collect|download|export|list|summarize|check|"
    r"monitor|calculate|compare|deploy|publish|ship)\b",
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
    return Path(override) if override else Path.home() / ".rote" / "play" / "intercept-index.json"


def _state_path() -> Path:
    override = os.environ.get("PLAY_INTERCEPT_STATE_PATH")
    return Path(override) if override else Path.home() / ".rote" / "play" / "intercept-state.json"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(text.casefold())
        if len(token) > 1 and token not in _STOPWORDS
    }


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


def best_match(prompt: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Score prompt tokens against name/tag (weight 3) and description (weight 1)."""

    prompt_tokens = _tokens(prompt)
    if not prompt_tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for entry in entries:
        name_hits = len(prompt_tokens & set(entry.get("name_tokens", [])))
        text_hits = len(prompt_tokens & set(entry.get("text_tokens", [])))
        score = name_hits * 3 + text_hits
        if score > best_score:
            best, best_score = entry, score
    if best is not None and best_score >= 4 and (
        len(prompt_tokens & set(best.get("name_tokens", []))) >= 2
    ):
        return best
    return None


def _silenced(prompt: str) -> bool:
    task_class = coarse_task_class(prompt)
    for policy in load_ledger():
        if policy.get("task_class") == task_class and policy.get("policy") == "silent":
            return True
    return False


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


def intercept_prompt(prompt: str) -> str | None:
    """Return the one context line to inject, or None for silence."""

    stripped = prompt.strip()
    if (
        len(stripped) < MIN_PROMPT_CHARS
        or stripped.startswith(("$play", "/play", "!", "/"))
        or _silenced(stripped)
    ):
        return None
    entries = load_index()
    match = best_match(stripped, entries)
    if match is not None:
        description = match.get("description") or "a saved Play"
        return (
            f"Play: saved Play `{match['reference']}` looks relevant — {description} "
            "Run it through the play skill instead of doing this manually."
        )
    if _FAST_OUTCOME.match(stripped) and entries is not None:
        state_path = _state_path()
        if _advice_recently_given(state_path):
            return None
        _record(state_path, advice_at_epoch=time.time())
        return (
            "Play: this looks like a repeatable outcome — have the play skill search "
            "preexisting saved Plays (local and authorized hubs) before doing it manually."
        )
    return None


def settle_nudge(session_id: str | None) -> str | None:
    """Return a one-time user-facing settle reminder for an armed, unsettled hook."""

    hook = latest_hook()
    if hook is None:
        return None
    hook_ref = hook.get("hook_ref")
    if not isinstance(hook_ref, str):
        return None
    state_path = _state_path()
    try:
        state = load_json(state_path)
    except (OSError, ValueError):
        state = None
    nudged = state.get("nudged_hooks") if isinstance(state, Mapping) else None
    nudged = list(nudged) if isinstance(nudged, list) else []
    marker = f"{session_id or 'session'}:{hook_ref}"
    if marker in nudged:
        return None
    _record(state_path, nudged_hooks=[*nudged[-19:], marker])
    intent = str(hook.get("intent") or "earlier work")[:80]
    return (
        f"Play: a save hook is armed for “{intent}” — if that work is done and repeatable, "
        "type $play settle <one-line summary> to judge whether it is worth saving."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-intercept", description=__doc__)
    parser.add_argument("command", choices=["prompt", "settle-nudge"])
    arguments = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if arguments.command == "prompt":
        prompt = payload.get("prompt")
        line = intercept_prompt(prompt) if isinstance(prompt, str) else None
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

    line = settle_nudge(payload.get("session_id"))
    if line:
        print(json.dumps({"systemMessage": line, "suppressOutput": True}))
    return 0
