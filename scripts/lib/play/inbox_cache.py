"""Zero-token Play inbox: a cached what's-new summary refreshed in the background.

The cache is written by a background refresh (stale-while-revalidate at session
start, or any scheduler) and read instantly without network or model work. It
stores two tiers: a precomputed one-line summary safe to inject into a session
banner, and the full digest payload plus rendered markdown for detail recall.
The interactive awareness lane owns the acknowledgment checkpoint; the refresh
reads that checkpoint without advancing it, so the line goes quiet only after
the user actually views the digest.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .digest import collect_digest, render_markdown
from .digest_state import (
    default_state_path,
    load_entry,
    scope_contract,
    scope_key,
)
from .private_store import atomic_write_json, load_json
from .registry import Organization, load_authorized_flows, load_organizations
from .render import json_text
from .state_home import state_path


CACHE_SCHEMA = "play.inbox-cache/v1"
DEFAULT_WINDOW_DAYS = 7


def _default_cache_path() -> Path:
    override = os.environ.get("PLAY_INBOX_CACHE_PATH")
    return Path(override) if override else state_path("inbox-cache.json")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def summary_line(digest: Mapping[str, Any]) -> str | None:
    """Build the one-line banner, or None when there is nothing new to say."""

    updates = digest.get("org_updates")
    if not isinstance(updates, Mapping):
        return None
    raw_new_items = updates.get("new")
    raw_revised_items = updates.get("revised")
    new_items: list[Any] = raw_new_items if isinstance(raw_new_items, list) else []
    revised_items: list[Any] = (
        raw_revised_items if isinstance(raw_revised_items, list) else []
    )
    if not new_items and not revised_items:
        return None
    window = digest.get("window")
    since = ""
    if isinstance(window, Mapping) and isinstance(window.get("start"), str):
        try:
            started = datetime.fromisoformat(window["start"])
            since = f" since {started.strftime('%b %-d')}"
        except ValueError:
            since = ""
    parts = []
    if new_items:
        parts.append(f"{len(new_items)} new Play{'s' if len(new_items) != 1 else ''}")
    if revised_items:
        parts.append(
            f"{len(revised_items)} revised Play{'s' if len(revised_items) != 1 else ''}"
        )
    owners = sorted(
        {
            str(item.get("owner"))
            for item in [*new_items, *revised_items]
            if isinstance(item, Mapping) and item.get("owner")
        }
    )
    where = f" in {', '.join(owners[:3])}" if owners else " in your organizations"
    return (
        "Play inbox: " + " and ".join(parts) + where + since + " — say \"what's new\" to see them."
    )


def refresh_cache(
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    cache_path: Path | None = None,
    state_path: Path | None = None,
    if_older_than_hours: float | None = None,
    collect: Callable[..., dict[str, Any]] | None = None,
    load_flows: Callable[[set[str]], dict[str, list[dict[str, Any]]]] | None = None,
    organizations: list[Organization] | None = None,
) -> dict[str, Any]:
    """Fetch the digest and persist both cache tiers; the background-job body."""

    target = cache_path or _default_cache_path()
    if if_older_than_hours is not None:
        existing = read_cache(cache_path=target)
        if existing is not None:
            fetched_at = existing.get("fetched_at")
            try:
                age = (_utc_now() - datetime.fromisoformat(str(fetched_at))).total_seconds()
                if age < if_older_than_hours * 3600:
                    return {**existing, "refreshed": False}
            except ValueError:
                pass

    resolved_organizations = (
        organizations if organizations is not None else load_organizations()
    )
    since: str | None = None
    # Mirror the interactive digest's default scope so the cache honors the
    # same acknowledgment checkpoint the awareness lane advances.
    scope = scope_contract(
        resolved_organizations,
        window_days=days,
        public_limit=10,
        inspection_budget=100,
        update_metadata_budget=100,
        update_inspection_budget=4,
    )
    entry = load_entry(state_path or default_state_path(), scope_key(scope))
    if entry is not None and entry.get("scope") == scope:
        since = entry["checkpoint"]["last_seen_at"]

    collector = collect or collect_digest
    digest = collector(days=days, since=since, organizations=resolved_organizations)
    flows_loader = load_flows or load_authorized_flows
    try:
        grouped = flows_loader({org.slug for org in resolved_organizations})
    except Exception:  # noqa: BLE001 - the catalog tier is best-effort
        grouped = {}
    catalog: list[dict[str, Any]] = []
    seen_references: set[str] = set()
    for slug, flows in grouped.items():
        if not isinstance(flows, list):
            continue
        for flow in flows:
            if not isinstance(flow, Mapping):
                continue
            name = flow.get("name")
            if not isinstance(name, str) or not name:
                continue
            reference = flow.get("reference")
            if not isinstance(reference, str) or not reference:
                reference = f"{slug}/{name}"
            if reference in seen_references:
                continue
            seen_references.add(reference)
            catalog_entry = {
                "reference": reference,
                "name": name,
                "description": str(flow.get("description") or "")[:240],
                "visibility": flow.get("visibility"),
            }
            for source_field, cache_field in (("id", "skill_id"), ("owner_id", "owner_id")):
                value = flow.get(source_field)
                if isinstance(value, str) and value:
                    catalog_entry[cache_field] = value
            catalog.append(catalog_entry)
            if len(catalog) >= 500:
                break
    try:
        markdown = render_markdown(dict(digest))
    except (KeyError, TypeError):
        markdown = None
    cache = {
        "schema": CACHE_SCHEMA,
        "fetched_at": _utc_now().isoformat(timespec="seconds"),
        "window_days": days,
        "summary_line": summary_line(digest),
        "counts": {
            "new": len(digest.get("org_updates", {}).get("new", [])),
            "revised": len(digest.get("org_updates", {}).get("revised", [])),
        },
        "digest": digest,
        "markdown": markdown,
        "catalog": catalog,
        "refreshed": True,
    }
    atomic_write_json(target, {key: value for key, value in cache.items() if key != "refreshed"})
    return cache


def read_cache(*, cache_path: Path | None = None) -> dict[str, Any] | None:
    """Read the cache without any network or model work."""

    target = cache_path or _default_cache_path()
    try:
        payload = load_json(target)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema") != CACHE_SCHEMA:
        return None
    return dict(payload)


def cached_line(*, cache_path: Path | None = None) -> str | None:
    """The zero-token session-start surface: one line, or nothing at all."""

    cache = read_cache(cache_path=cache_path)
    if cache is None:
        return None
    line = cache.get("summary_line")
    return line if isinstance(line, str) and line.strip() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play-inbox", description=__doc__)
    parser.add_argument("command", choices=["refresh", "line", "details"])
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--if-older-than",
        type=float,
        metavar="HOURS",
        help="refresh only when the cache is older than this many hours",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)

    if arguments.command == "refresh":
        if arguments.days < 1:
            parser.error("--days must be at least 1")
        try:
            cache = refresh_cache(
                days=arguments.days, if_older_than_hours=arguments.if_older_than
            )
        except Exception as error:  # noqa: BLE001 - background job must fail quietly
            print(f"play-inbox: {error}", file=sys.stderr)
            return 1
        if arguments.as_json:
            print(json_text({k: v for k, v in cache.items() if k != "digest"}))
        else:
            print(cache.get("summary_line") or "Nothing new since your last Play check.")
        return 0

    cache = read_cache()
    if arguments.command == "line":
        line = cached_line()
        if arguments.as_json:
            print(json_text({"schema": CACHE_SCHEMA, "line": line}))
        elif line:
            print(line)
        return 0

    if cache is None:
        print("play-inbox: no cached inbox yet; run play-inbox refresh", file=sys.stderr)
        return 1
    if arguments.as_json:
        print(json_text(cache))
    else:
        print(cache.get("markdown") or "")
    return 0
