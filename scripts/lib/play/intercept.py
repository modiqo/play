"""Point actionable prompts at rote guidance and suggest direct published Plays.

The rote pointer does not depend on discovery. The Play suggestion stays silent on
timeout, failed identity, or uncertain relevance, and never uses local catalogs or
unpublished Plays to decide relevance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

MIN_PROMPT_CHARS = 8
ROTE_POINTER = (
    "rote: for API, MCP, browser, registry, or automation work, run "
    "`rote guidance root` and follow it."
)
_BYPASS_PREFIXES = ("direct:", "without play:")
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


def is_bare_hello_request(prompt: str) -> bool:
    """Keep an unprefixed Hello request on the normal agent route."""

    return _BARE_HELLO_REQUEST.fullmatch(prompt.strip()) is not None


def is_action_request(prompt: str) -> bool:
    """Avoid network discovery for discussion questions."""

    stripped = prompt.strip()
    return (
        _DISCUSSION_REQUEST.match(stripped) is None
        and _ACTION_REQUEST.match(stripped) is not None
    )


def _is_match_backed_request(prompt: str) -> bool:
    """Allow request prefixes when an action verb may be misspelled."""

    stripped = prompt.strip()
    return (
        _DISCUSSION_REQUEST.match(stripped) is None
        and _PREFIXED_DISCUSSION.match(stripped) is None
        and _REQUEST_PREFIX.match(stripped) is not None
    )


def _play_suggestion(prompt: str) -> str | None:
    """Return a Worker-confirmed direct Play suggestion, or None."""

    # Any discovery failure (imports, identity, network, judgment) only drops the
    # suggestion; the rote pointer is composed independently.
    try:
        from .search import search_published

        result = search_published(prompt, limit=3, timeout_seconds=3.0)
    except Exception:
        return None
    matches = [
        item for item in result["results"] if item.get("relevance_status") == "direct"
    ]
    if result["source_health"].get("mode") != "judged" or not matches:
        return None
    reference = matches[0]["exact_reference"]
    return (
        f"Play suggestion: Worker-confirmed direct match `{reference}`. "
        "Show one quiet, non-blocking line: "
        f'"Play found: `{reference}` — explicitly invoke Play with '
        f'`{reference}` to inspect it." Do not enter the Play state '
        "machine, load Play or Rote state, pause, or change the original request."
    )


def intercept_prompt(
    prompt: str,
    *,
    session_id: str | None = None,
    project_path: str | None = None,
) -> str | None:
    """Return the context to inject, or None for silence."""

    stripped = prompt.strip()
    if is_bare_hello_request(stripped):
        return None
    if len(stripped) < MIN_PROMPT_CHARS or stripped.startswith(
        ("$play", "/play", "!", "/")
    ):
        return None
    if stripped.lower().startswith(_BYPASS_PREFIXES):
        return None
    action_request = is_action_request(stripped)
    if not action_request and not _is_match_backed_request(stripped):
        return None
    suggestion = _play_suggestion(stripped)
    return ROTE_POINTER if suggestion is None else f"{ROTE_POINTER}\n{suggestion}"


def milestone_nudge(session_id: str | None) -> str | None:
    """Return an explicit workflow's exploration pulse or achievement nudge."""

    from .journal import claim_exploration_pulse, render_pulse
    from .milestones import claim_nudge

    pulse = claim_exploration_pulse(session_id=session_id)
    return (
        render_pulse(pulse) if pulse is not None else claim_nudge(session_id=session_id)
    )


def settle_nudge(session_id: str | None) -> str | None:
    """Compatibility alias for hooks installed before milestone nudges."""

    return milestone_nudge(session_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-intercept", description=__doc__)
    parser.add_argument(
        "command", choices=["prompt", "milestone-nudge", "settle-nudge"]
    )
    parser.add_argument(
        "--harness",
        choices=["cursor"],
        help="emit this harness's hook response shape instead of Claude/Codex's",
    )
    arguments = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if arguments.command == "prompt" and arguments.harness == "cursor":
        # Cursor's beforeSubmitPrompt response can only allow or block the
        # prompt; it has no field that injects context, so skip discovery.
        print(json.dumps({"continue": True}))
        return 0

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
    # valid but inert until `rote install play` rewrites the stale hook entries.
    return 0
