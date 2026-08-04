"""Read-only Play awareness digest aggregation and rendering."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from .registry import (
    RegistryReadError,
    load_authorized_flows,
    load_organizations,
    load_public_flows,
)
from .render import compact_json, json_text


SCHEMA = "play.digest/v1"


class DigestError(RegistryReadError):
    pass


def parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DigestError(f"{field} is missing or invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise DigestError(f"{field} is not an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise DigestError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _digest_item(slug: str, flow: dict[str, Any], timestamp: datetime, kind: str) -> dict[str, Any]:
    parameters = flow.get("default_parameters")
    return {
        "reference": f"{slug}/{flow['name']}",
        "name": flow["name"],
        "owner": slug,
        "description": flow.get("description") or "",
        "visibility": flow["visibility"],
        "kind": kind,
        "timestamp": timestamp.isoformat(),
        "version": flow.get("version"),
        "parameters": parameters if isinstance(parameters, dict) else {},
    }


def classify_updates(
    grouped: dict[str, list[dict]], start: datetime, end: datetime
) -> tuple[list[dict], list[dict]]:
    new: list[dict] = []
    revised: list[dict] = []
    for slug, flows in grouped.items():
        for flow in flows:
            created = parse_timestamp(flow.get("created_at"), field=f"{slug}/{flow['name']}.created_at")
            latest_value = flow.get("latest_version_created_at") or flow.get("updated_at")
            latest = parse_timestamp(latest_value, field=f"{slug}/{flow['name']}.updated_at")
            if start <= created < end:
                new.append(_digest_item(slug, flow, created, "new"))
            elif start <= latest < end and latest > created:
                revised.append(_digest_item(slug, flow, latest, "revised"))
    order = lambda item: (-parse_timestamp(item["timestamp"], field="timestamp").timestamp(), item["reference"])
    new.sort(key=order)
    revised.sort(key=order)
    return new, revised


def rank_public(flows: list[tuple[str, dict]], limit: int) -> tuple[list[dict], dict[str, Any]]:
    eligible: list[dict] = []
    for slug, flow in flows:
        if flow.get("visibility") != "public" or flow.get("deleted_at"):
            continue
        status = flow.get("status")
        if status is not None and status not in {"approved", "released"}:
            continue
        if flow.get("play_run_eligible") is False:
            continue
        downloads = flow.get("download_count")
        if not isinstance(downloads, int) or downloads < 0:
            continue
        parameters = flow.get("default_parameters")
        eligible.append(
            {
                "reference": f"{slug}/{flow['name']}",
                "name": flow["name"],
                "owner": slug,
                "description": flow.get("description") or "",
                "visibility": "public",
                "version": flow.get("version"),
                "download_count": downloads,
                "parameters": parameters if isinstance(parameters, dict) else {},
            }
        )
    eligible.sort(key=lambda item: (-item["download_count"], item["reference"]))
    ranking = {
        "metric": "lifetime_downloads",
        "label": "Most downloaded public Plays overall",
        "eligible_count": len(eligible),
        "complete": bool(eligible),
    }
    if not eligible:
        ranking["reason"] = "registry list did not expose comparable download counts"
    return eligible[:limit], ranking


def build_digest(
    organizations,
    grouped: dict[str, list[dict]],
    public_flows: list[tuple[str, dict]],
    *,
    start: datetime,
    end: datetime,
    public_limit: int,
) -> dict[str, Any]:
    new, revised = classify_updates(grouped, start, end)
    public_top, ranking = rank_public(public_flows, public_limit)
    return {
        "schema": SCHEMA,
        "complete": True,
        "window": {
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
            "timezone": "UTC",
        },
        "sources": ["authorized_registry", "public_registry"],
        "organizations": [
            {"slug": org.slug, "display_name": org.display_name} for org in organizations
        ],
        "org_updates": {"new": new, "revised": revised},
        "public_top": public_top,
        "ranking": ranking,
        "personal_stats": {
            "status": "unavailable",
            "reason": "registry inventory does not yet expose attributable creator and verified-run metrics",
        },
    }


def render_markdown(digest: dict[str, Any]) -> str:
    window = digest["window"]
    lines = [
        "# Play digest",
        "",
        f"Window: `{window['start']}` to `{window['end']}`",
    ]
    for key, title in (("new", "New in your organizations"), ("revised", "Revised in your organizations")):
        items = digest["org_updates"][key]
        lines.extend(["", f"## {title} ({len(items)})", ""])
        if items:
            for item in items:
                parameters = compact_json(item["parameters"])
                lines.append(
                    f"- `{item['reference']}` · {item['visibility']} · {item['timestamp']} "
                    f"· parameters `{parameters}`"
                )
        else:
            lines.append("— None")
    ranking = digest["ranking"]
    lines.extend(["", f"## {ranking['label']} ({len(digest['public_top'])})", ""])
    if digest["public_top"]:
        for item in digest["public_top"]:
            parameters = compact_json(item["parameters"])
            lines.append(
                f"- `{item['reference']}` · {item['download_count']} downloads "
                f"· parameters `{parameters}`"
            )
    else:
        lines.append(f"— Unavailable: {ranking.get('reason', 'no eligible public Plays')}")
    stats = digest["personal_stats"]
    lines.extend(["", "## Your impact", "", f"— Unavailable: {stats['reason']}"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--public-limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.days < 1 or args.public_limit < 1:
        parser.error("--days and --public-limit must be at least 1")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    try:
        organizations = load_organizations()
        grouped = load_authorized_flows({org.slug for org in organizations})
        public = load_public_flows()
        digest = build_digest(
            organizations,
            grouped,
            public,
            start=start,
            end=end,
            public_limit=args.public_limit,
        )
    except RegistryReadError as error:
        print(f"play-digest: {error}", file=sys.stderr)
        return 1
    print(json_text(digest) if args.as_json else render_markdown(digest))
    return 0
