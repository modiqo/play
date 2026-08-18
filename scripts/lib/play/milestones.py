"""Owner-private Play achievement events and one-time learning nudges."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .private_store import atomic_write_json, load_json
from .state_home import state_path


SCHEMA = "play.milestones/v1"
MAX_EVENTS = 64
EVENT_KINDS = (
    "play_run_completed",
    "play_created",
    "play_shared_private",
    "play_published_public",
)
_PRIORITY = {kind: index for index, kind in enumerate(EVENT_KINDS)}

_NUDGES = {
    "play_run_completed": (
        "🎭 **Playrunner unlocked**\n\n"
        "Congrats—you just ran your first Play, so you’re officially a **playrunner**. "
        "Run one directly with `$play <play URI>`, or simply ask for an outcome with "
        "`$play <what you want in English>`.\n\n"
        "Ready to become a **playmaker**? Try `$play explore <something useful>` and "
        "guide the agent as the Play takes shape—your expertise matters. When the result "
        "is repeatable, say **save this Play**, then share it privately with teammates or "
        "publicly with the community."
    ),
    "play_created": (
        "🛠️ **Playmaker unlocked**\n\n"
        "You turned working expertise into a reusable Play. Run it again, refine it with "
        "real feedback, then share it privately with teammates or publicly with the community."
    ),
    "play_shared_private": (
        "🤝 **Team playmaker unlocked**\n\n"
        "Your Play is now shared privately. Invite a teammate to run it—the best team Plays "
        "improve when domain experts guide them with real edge cases."
    ),
    "play_published_public": (
        "🌍 **Community playmaker unlocked**\n\n"
        "Your Play is now discoverable by the community. Each successful run can turn your "
        "expertise into someone else’s head start."
    ),
}


def _path() -> Path:
    override = os.environ.get("PLAY_MILESTONE_PATH")
    return Path(override) if override else state_path("milestones.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = load_json(path)
    except (OSError, ValueError):
        value = None
    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "events": [], "claimed_event_ids": []}
    events = value.get("events")
    claimed = value.get("claimed_event_ids")
    return {
        "schema": SCHEMA,
        "events": list(events) if isinstance(events, list) else [],
        "claimed_event_ids": list(claimed) if isinstance(claimed, list) else [],
    }


def _write(path: Path, store: Mapping[str, Any]) -> None:
    try:
        atomic_write_json(path, dict(store))
    except OSError:
        # Achievement coaching must never interrupt the Play that earned it.
        pass


def record_event(
    kind: str,
    *,
    run_id: str | None = None,
    reference: str | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Record the first unlock of one milestone kind without storing secrets."""

    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown Play milestone event {kind!r}")
    target = path or _path()
    store = _load(target)
    events = [event for event in store["events"] if isinstance(event, Mapping)]
    if any(event.get("kind") == kind for event in events):
        return None
    identity = {
        "kind": kind,
        "run_id": run_id if isinstance(run_id, str) else None,
        "reference": reference if isinstance(reference, str) else None,
    }
    event_id = "evt_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    event = {
        "schema": "play.milestone-event/v1",
        "id": event_id,
        "kind": kind,
        "occurred_at": _now(),
        **({"run_id": run_id} if isinstance(run_id, str) and run_id else {}),
        **(
            {"reference": reference}
            if isinstance(reference, str) and reference
            else {}
        ),
    }
    store["events"] = [*events, event][-MAX_EVENTS:]
    _write(target, store)
    return event


def observe_transition(
    *,
    source: str,
    event: str,
    target: str,
    context: Mapping[str, Any],
    path: Path | None = None,
) -> None:
    """Translate successful typed controller transitions into milestones."""

    kind = None
    if source == "use_receipt" and event == "receipt_ready" and target in {
        "receipt",
        "onboarding_result_offer",
    }:
        kind = "play_run_completed"
    elif source == "author_release" and event == "flow_released" and target == "birth_capture":
        kind = "play_created"
    elif source == "private_publish" and event == "play_published" and target == "birth_bind":
        kind = "play_shared_private"
    elif source == "public_publish" and event == "play_published" and target == "birth_bind":
        kind = "play_published_public"
    if kind is None:
        return
    reference = _reference(context)
    run_id = context.get("run_id")
    record_event(
        kind,
        run_id=run_id if isinstance(run_id, str) else None,
        reference=reference,
        path=path,
    )


def _reference(context: Mapping[str, Any]) -> str | None:
    for parent, field in (
        ("publication", "canonical_reference"),
        ("candidate", "released_flow"),
        ("match", "reference"),
    ):
        value = context.get(parent)
        if not isinstance(value, Mapping):
            continue
        reference = value.get(field)
        if isinstance(reference, str) and reference:
            return reference
    return None


def claim_nudge(
    *, session_id: str | None = None, path: Path | None = None
) -> str | None:
    """Claim the highest unlocked, unshown milestone and return its coaching."""

    target = path or _path()
    store = _load(target)
    claimed = {
        value for value in store["claimed_event_ids"] if isinstance(value, str)
    }
    pending = [
        event
        for event in store["events"]
        if isinstance(event, Mapping)
        and event.get("kind") in _PRIORITY
        and isinstance(event.get("id"), str)
        and event["id"] not in claimed
    ]
    if not pending:
        return None
    selected = max(pending, key=lambda event: _PRIORITY[str(event["kind"])])
    selected_priority = _PRIORITY[str(selected["kind"])]
    # Coalesce lower achievements unlocked in the same uninterrupted journey.
    # The user sees the highest meaningful progress message, never a queue of
    # stale congratulatory Stop hooks.
    consumed = {
        str(event["id"])
        for event in pending
        if _PRIORITY[str(event["kind"])] <= selected_priority
    }
    store["claimed_event_ids"] = sorted(claimed | consumed)
    store["last_claim"] = {
        "event_id": selected["id"],
        "claimed_at": _now(),
        **({"session_id": session_id} if isinstance(session_id, str) else {}),
    }
    _write(target, store)
    return _NUDGES[str(selected["kind"])]
