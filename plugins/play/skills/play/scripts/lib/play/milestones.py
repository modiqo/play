"""Owner-private Play achievements and repeatable event-backed learning nudges."""

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

_REPEAT_PREFIXES = {
    "play_run_completed": "🎭 **Play complete**",
    "play_created": "🛠️ **Play created**",
    "play_shared_private": "🤝 **Team Play shared**",
    "play_published_public": "🌍 **Community Play published**",
}

_REPEAT_COACHING = {
    "play_run_completed": (
        "Run another outcome with `$play <what you want in English>`, or say **save this Play** if this run revealed a reusable improvement.",
        "Want a variation? Ask with `$play <the next outcome>`; when the method becomes repeatable, say **save this Play**.",
        "Keep the momentum with `$play <play URI>` or a plain-English outcome. If your guidance improved the method, say **save this Play**.",
    ),
    "play_created": (
        "Try one real edge case next, then share the Play privately with teammates or publicly with the community.",
        "Run it once with different inputs; the best reusable Plays improve through real feedback.",
        "Your expertise is reusable now. Invite a teammate to test it, or publish it when the method is ready for the community.",
    ),
    "play_shared_private": (
        "Ask a teammate to run it with a real edge case—their feedback can sharpen the shared method.",
        "The next level is team reuse: have someone else run it, then fold their domain guidance back into the Play.",
        "One teammate run will teach you more than another draft. Use their feedback to refine the Play.",
    ),
    "play_published_public": (
        "Try finding it by outcome or adapter—the community experience starts with successful discovery.",
        "Share the outcome it unlocks, not just its name, so the right people can discover and run it.",
        "Watch how others use it; community edge cases are fuel for the next revision.",
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
        return {
            "schema": SCHEMA,
            "events": [],
            "claimed_event_ids": [],
            "unlocked_kinds": [],
        }
    events = value.get("events")
    claimed = value.get("claimed_event_ids")
    event_values = list(events) if isinstance(events, list) else []
    claimed_values = list(claimed) if isinstance(claimed, list) else []
    unlocked = value.get("unlocked_kinds")
    if isinstance(unlocked, list):
        unlocked_values = [kind for kind in unlocked if kind in EVENT_KINDS]
    else:
        claimed_ids = {item for item in claimed_values if isinstance(item, str)}
        unlocked_values = [
            str(event["kind"])
            for event in event_values
            if isinstance(event, Mapping)
            and event.get("id") in claimed_ids
            and event.get("kind") in EVENT_KINDS
        ]
    return {
        "schema": SCHEMA,
        "events": event_values,
        "claimed_event_ids": claimed_values,
        "unlocked_kinds": list(dict.fromkeys(unlocked_values)),
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
    """Record one unique achievement event without storing secrets."""

    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown Play milestone event {kind!r}")
    target = path or _path()
    store = _load(target)
    events = [event for event in store["events"] if isinstance(event, Mapping)]
    identity = {"kind": kind}
    if isinstance(run_id, str) and run_id:
        identity["run_id"] = run_id
    elif isinstance(reference, str) and reference:
        identity["reference"] = reference
    event_id = "evt_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    if any(event.get("id") == event_id for event in events):
        return None
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
    unlocked = {
        value for value in store.get("unlocked_kinds", []) if value in EVENT_KINDS
    }
    selected_kind = str(selected["kind"])
    first_unlock = selected_kind not in unlocked
    unlocked.update(
        str(event["kind"])
        for event in pending
        if str(event["id"]) in consumed
    )
    store["claimed_event_ids"] = sorted(claimed | consumed)
    store["unlocked_kinds"] = sorted(unlocked, key=_PRIORITY.__getitem__)
    store["last_claim"] = {
        "event_id": selected["id"],
        "kind": selected_kind,
        "claimed_at": _now(),
        **({"session_id": session_id} if isinstance(session_id, str) else {}),
    }
    _write(target, store)
    if first_unlock:
        return _NUDGES[selected_kind]
    return _repeat_nudge(selected)


def _repeat_nudge(event: Mapping[str, Any]) -> str:
    kind = str(event["kind"])
    choices = _REPEAT_COACHING[kind]
    event_id = str(event["id"])
    choice = choices[int(hashlib.sha256(event_id.encode()).hexdigest()[:8], 16) % len(choices)]
    reference = event.get("reference")
    subject = (
        f" `{reference}`"
        if isinstance(reference, str) and reference
        else ""
    )
    return f"{_REPEAT_PREFIXES[kind]}{subject}\n\n{choice}"
