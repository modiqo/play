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
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .digest import collect_digest, render_markdown, supports_play_discovery
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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {item.strip() for item in value if isinstance(item, str) and item.strip()},
        key=str.casefold,
    )


def _public_catalog_entry(slug: str, flow: Mapping[str, Any]) -> dict[str, Any] | None:
    if flow.get("visibility") != "public" or flow.get("deleted_at"):
        return None
    status = flow.get("status")
    if status is not None and status not in {"approved", "released"}:
        return None
    if flow.get("play_run_eligible") is False:
        return None
    name = flow.get("name")
    if not isinstance(name, str) or not name:
        return None
    reference = (
        flow.get("base_reference") or flow.get("reference") or f"{slug}/{name}"
    )
    if not isinstance(reference, str) or not reference:
        return None
    reference = reference.partition("@")[0]
    version = flow.get("version")
    exact_reference = flow.get("exact_reference")
    if not isinstance(exact_reference, str) or not exact_reference:
        exact_reference = (
            f"{reference}@{version}"
            if isinstance(version, str) and version
            else reference
        )
    entry: dict[str, Any] = {
        "reference": reference,
        "exact_reference": exact_reference,
        "owner": slug,
        "name": name,
        "description": str(flow.get("description") or "")[:240],
        "visibility": "public",
        "version": version if isinstance(version, str) and version else None,
        "status": status if isinstance(status, str) and status else None,
        "created_at": (
            flow.get("created_at")
            if isinstance(flow.get("created_at"), str)
            else None
        ),
        "latest_version_created_at": (
            flow.get("latest_version_created_at")
            if isinstance(flow.get("latest_version_created_at"), str)
            else None
        ),
        "labels": _string_list(flow.get("labels")),
        "tags": _string_list(flow.get("tags")),
    }
    for source_field, cache_field in (("id", "skill_id"), ("owner_id", "owner_id")):
        value = flow.get(source_field)
        if isinstance(value, str) and value:
            entry[cache_field] = value
    return entry


def _snapshot_sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def refresh_cache(
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    cache_path: Path | None = None,
    state_path: Path | None = None,
    if_older_than_hours: float | None = None,
    collect: Callable[..., dict[str, Any]] | None = None,
    load_flows: Callable[[set[str]], dict[str, list[dict[str, Any]]]] | None = None,
    organizations: list[Organization] | None = None,
    require_complete_catalog: bool = False,
) -> dict[str, Any]:
    """Fetch the digest and persist both cache tiers; the background-job body."""

    target = cache_path or _default_cache_path()
    if if_older_than_hours is not None:
        existing = read_cache(cache_path=target)
        if existing is not None:
            fetched_at = existing.get("fetched_at")
            try:
                age = (_utc_now() - datetime.fromisoformat(str(fetched_at))).total_seconds()
                if age < if_older_than_hours * 3600 and supports_play_discovery(
                    existing.get("digest")
                ):
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

    flows_loader = load_flows or load_authorized_flows
    catalog_complete = True
    try:
        grouped = flows_loader({org.slug for org in resolved_organizations})
    except Exception:  # noqa: BLE001 - retain a prior verified snapshot on maintenance failure
        if require_complete_catalog:
            raise
        existing = read_cache(cache_path=target)
        if existing is not None:
            return {**existing, "refreshed": False}
        raise
    collector = collect or collect_digest
    digest = collector(
        days=days,
        since=since,
        organizations=resolved_organizations,
        grouped_flows=grouped,
    )
    catalog: list[dict[str, Any]] = []
    public_catalog: list[dict[str, Any]] = []
    seen_references: set[str] = set()
    for slug in sorted(grouped):
        flows = grouped[slug]
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
            public_entry = _public_catalog_entry(slug, flow)
            if public_entry is not None:
                public_catalog.append(public_entry)
    catalog.sort(key=lambda item: str(item["reference"]).casefold())
    public_catalog.sort(
        key=lambda item: (str(item["reference"]).casefold(), str(item["exact_reference"]))
    )
    organization_scope = sorted({org.slug for org in resolved_organizations})
    catalog_snapshot = {
        "organization_scope": organization_scope,
        "plays": public_catalog,
    }
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
            "public": len(public_catalog),
        },
        "catalog_complete": catalog_complete,
        "organization_scope": organization_scope,
        "catalog_sha256": _snapshot_sha(catalog_snapshot),
        "digest": digest,
        "markdown": markdown,
        "catalog": catalog,
        "public_catalog": public_catalog,
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
    parser.add_argument(
        "--require-complete-catalog",
        action="store_true",
        help="fail instead of replacing the cache when the authorized catalog cannot be loaded",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)

    if arguments.command == "refresh":
        if arguments.days < 1:
            parser.error("--days must be at least 1")
        try:
            cache = refresh_cache(
                days=arguments.days,
                if_older_than_hours=arguments.if_older_than,
                require_complete_catalog=arguments.require_complete_catalog,
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
