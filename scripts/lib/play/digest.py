"""Read-only Play awareness digest aggregation and rendering."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .registry import (
    RegistryReadError,
    InspectionBatch,
    Organization,
    inspect_authorized_public_flows,
    inspect_references,
    load_authorized_flows,
    load_organizations,
)
from .render import compact_json, json_text
from .timewindow import TimeWindowError, next_checkpoint, parse_timestamp, resolve_window


SCHEMA = "play.digest/v1"


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
            if start <= created < end:
                new.append(_digest_item(slug, flow, created, "new"))
                continue
            latest_value = flow.get("latest_version_created_at")
            if latest_value is not None:
                latest = parse_timestamp(
                    latest_value,
                    field=f"{slug}/{flow['name']}.latest_version_created_at",
                )
                if start <= latest < end and latest > created:
                    revised.append(_digest_item(slug, flow, latest, "revised"))
    order = lambda item: (-parse_timestamp(item["timestamp"], field="timestamp").timestamp(), item["reference"])
    new.sort(key=order)
    revised.sort(key=order)
    return new, revised


def rank_public(
    flows: list[tuple[str, dict]],
    limit: int,
    *,
    source_complete: bool = True,
    source_errors: list[str] | None = None,
    candidate_count: int | None = None,
    omitted_count: int = 0,
) -> tuple[list[dict], dict[str, Any]]:
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
        base_reference = flow.get("reference") or f"{slug}/{flow['name']}"
        version = flow.get("version")
        exact_reference = flow.get("exact_reference") or (
            f"{base_reference}@{version}" if version else base_reference
        )
        eligible.append(
            {
                "reference": exact_reference,
                "base_reference": base_reference,
                "name": flow["name"],
                "owner": slug,
                "description": flow.get("description") or "",
                "visibility": "public",
                "version": flow.get("version"),
                "download_count": downloads,
                "install_count": flow.get("install_count"),
                "parameters": parameters if isinstance(parameters, dict) else {},
            }
        )
    eligible.sort(key=lambda item: (-item["download_count"], item["reference"]))
    ranking = {
        "metric": "lifetime_downloads",
        "label": (
            "Most downloaded public Plays in your organizations"
            if source_complete
            else "Most downloaded inspected public Plays in your organizations"
        ),
        "scope": "authorized_organizations",
        "eligible_count": len(eligible),
        "candidate_count": candidate_count if candidate_count is not None else len(flows),
        "inspected_count": len(flows),
        "omitted_count": omitted_count,
        "complete": source_complete,
        "global_status": "unavailable",
        "global_reason": "registry exposes no canonical global public enumeration",
    }
    if source_errors:
        ranking["errors"] = source_errors
    if not source_complete:
        ranking["reason"] = "one or more public Plays could not be inspected"
    elif not eligible:
        ranking["reason"] = "no run-eligible public Plays were found in authorized organizations"
    return eligible[:limit], ranking


def build_digest(
    organizations,
    grouped: dict[str, list[dict]],
    public_flows: list[tuple[str, dict]],
    *,
    start: datetime,
    end: datetime,
    public_limit: int,
    ranking_complete: bool = True,
    ranking_errors: list[str] | None = None,
    ranking_candidate_count: int | None = None,
    ranking_omitted_count: int = 0,
    update_inspections: dict[str, dict[str, Any]] | None = None,
    update_inspection_errors: list[str] | None = None,
    update_omitted_count: int = 0,
) -> dict[str, Any]:
    new, revised = classify_updates(grouped, start, end)
    inspected_updates = update_inspections or {}
    for item in [*new, *revised]:
        base_reference = item["reference"]
        inspected = inspected_updates.get(base_reference)
        item["base_reference"] = base_reference
        item["actionable"] = inspected is not None
        if inspected is not None:
            item["reference"] = inspected["exact_reference"]
            item["version"] = inspected.get("version")
            item["parameters"] = inspected.get("default_parameters", {})
    revision_complete = all(
        flow.get("latest_version_created_at") is not None
        for flows in grouped.values()
        for flow in flows
        if parse_timestamp(
            flow.get("created_at"), field=f"{flow['name']}.created_at"
        ) < start
    )
    public_top, ranking = rank_public(
        public_flows,
        public_limit,
        source_complete=ranking_complete,
        source_errors=ranking_errors,
        candidate_count=ranking_candidate_count,
        omitted_count=ranking_omitted_count,
    )
    return {
        "schema": SCHEMA,
        "complete": True,
        "window": {
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
            "timezone": "UTC",
        },
        "sources": ["authorized_registry", "play_inspect"],
        "organizations": [
            {"slug": org.slug, "display_name": org.display_name} for org in organizations
        ],
        "org_updates": {
            "new": new,
            "revised": revised,
            "revised_complete": revision_complete,
        },
        "public_top": public_top,
        "ranking": ranking,
        "capabilities": {
            "organization_updates": {
                "new": {"status": "available"},
                "revised": {
                    "status": "available" if revision_complete else "unavailable",
                    "reason": (
                        None
                        if revision_complete
                        else "registry list lacks released-version timestamps"
                    ),
                },
                "actionable": {
                    "status": (
                        "available"
                        if not update_inspection_errors and update_omitted_count == 0
                        else "partial"
                    ),
                    "omitted_count": update_omitted_count,
                    "errors": update_inspection_errors or [],
                },
            },
            "public_ranking": {
                "status": "available" if ranking["complete"] else "partial",
                "scope": ranking["scope"],
            },
            "global_public_ranking": {
                "status": ranking["global_status"],
                "reason": ranking["global_reason"],
            },
            "personal_attribution": {
                "status": "unavailable",
                "missing": ["creator identity on publications", "persistent verified receipts"],
            },
        },
        "personal_stats": {
            "status": "unavailable",
            "reason": "registry inventory does not yet expose attributable creator and verified-run metrics",
        },
        "next_checkpoint": next_checkpoint(end),
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
        if key == "revised" and not digest["org_updates"]["revised_complete"]:
            lines.append("— Unavailable: registry list lacks released-version timestamps")
            continue
        if items:
            for item in items:
                parameters = compact_json(item["parameters"])
                lines.append(
                    f"- `{item['reference']}` · {item['visibility']} · {item['timestamp']} "
                    f"· parameters `{parameters}`"
                    + ("" if item.get("actionable") else " · inspect required before Use")
                )
        else:
            lines.append("— None")
    ranking = digest["ranking"]
    lines.extend(["", f"## {ranking['label']} ({len(digest['public_top'])})", ""])
    lines.append("Scope: authorized organizations; global public ranking is unavailable.")
    if not ranking["complete"]:
        lines.append("Coverage is partial because one or more public Plays could not be inspected.")
    lines.append("")
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
    parser.add_argument("--since", help="ISO-8601 start timestamp supplied by the host")
    parser.add_argument("--checkpoint", type=Path, help="read a host-persisted checkpoint token")
    parser.add_argument("--public-limit", type=int, default=5)
    parser.add_argument(
        "--inspection-budget",
        type=int,
        default=8,
        help="maximum authorized public Plays to inspect for ranking",
    )
    parser.add_argument(
        "--update-inspection-budget",
        type=int,
        default=4,
        help="maximum new or revised Plays to inspect for exact Use choices",
    )
    parser.add_argument(
        "--org",
        action="append",
        default=[],
        help="authorized organization slug; repeat to bypass organization discovery",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if (
        args.days < 1
        or args.public_limit < 1
        or args.inspection_budget < 1
        or args.update_inspection_budget < 1
    ):
        parser.error("digest limits and budgets must be at least 1")
    try:
        start, end = resolve_window(
            end=datetime.now(timezone.utc),
            days=args.days,
            since=args.since,
            checkpoint=args.checkpoint,
        )
        organizations = (
            [Organization(slug, slug) for slug in sorted(set(args.org))]
            if args.org
            else load_organizations()
        )
        grouped = load_authorized_flows({org.slug for org in organizations})
        candidate_new, candidate_revised = classify_updates(grouped, start, end)
        update_batch = inspect_references(
            [item["reference"] for item in [*candidate_new, *candidate_revised]],
            limit=args.update_inspection_budget,
        )
        update_inspections = {flow["reference"]: flow for _, flow in update_batch.flows}
        inspected: InspectionBatch = inspect_authorized_public_flows(
            grouped,
            limit=args.inspection_budget,
        )
        digest = build_digest(
            organizations,
            grouped,
            inspected.flows,
            start=start,
            end=end,
            public_limit=args.public_limit,
            ranking_complete=not inspected.errors and inspected.omitted_count == 0,
            ranking_errors=inspected.errors,
            ranking_candidate_count=inspected.candidate_count,
            ranking_omitted_count=inspected.omitted_count,
            update_inspections=update_inspections,
            update_inspection_errors=update_batch.errors,
            update_omitted_count=update_batch.omitted_count,
        )
    except (RegistryReadError, TimeWindowError) as error:
        print(f"play-digest: {error}", file=sys.stderr)
        return 1
    print(json_text(digest) if args.as_json else render_markdown(digest))
    return 0
