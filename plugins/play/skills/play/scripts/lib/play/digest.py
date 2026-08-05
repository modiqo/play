"""Play awareness digest aggregation, comparison, and rendering."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .digest_state import (
    DEFAULT_STATE_PATH,
    DigestStateError,
    compare_digest,
    load_entry,
    save_entry,
    scope_contract,
    scope_key,
    stable_sha,
)
from .registry import (
    RegistryReadError,
    InspectionBatch,
    Organization,
    inspect_references,
    load_authorized_public_flow_infos,
    load_authorized_flows,
    load_registry_flow_infos,
    load_organizations,
)
from .render import json_text
from .timewindow import TimeWindowError, next_checkpoint, parse_timestamp, resolve_window


SCHEMA = "play.digest/v1"
FINGERPRINT_FIELDS = (
    "name",
    "visibility",
    "created_at",
    "latest_version_created_at",
    "deleted_at",
    "status",
    "version",
)


def _digest_item(slug: str, flow: dict[str, Any], timestamp: datetime, kind: str) -> dict[str, Any]:
    parameters = flow.get("default_parameters")
    return {
        "reference": f"{slug}/{flow['name']}",
        "name": flow["name"],
        "owner": slug,
        "description": flow.get("description") or "",
        "creator_name": None,
        "creator_status": "unavailable",
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
                "creator_name": flow.get("creator_name"),
                "creator_status": flow.get("creator_status", "unavailable"),
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
            "Top public Plays by lifetime downloads in your organizations"
            if source_complete
            else "Top inspected public Plays by lifetime downloads in your organizations"
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
        ranking["reason"] = "one or more public Plays could not be read"
    elif not eligible:
        ranking["reason"] = (
            "no released public Plays with lifetime download totals were found in authorized "
            "organizations"
        )
    return eligible[:limit], ranking


def awareness_fingerprint(
    organizations: list[Organization],
    grouped: dict[str, list[dict]],
    public_top: list[dict[str, Any]],
    ranking: dict[str, Any],
) -> str:
    """Hash the current awareness snapshot without moving window timestamps."""

    snapshot = {
        "organizations": [org.slug for org in organizations],
        "plays": [
            {
                "owner": slug,
                **{field: flow.get(field) for field in FINGERPRINT_FIELDS},
            }
            for slug in sorted(grouped)
            for flow in sorted(grouped[slug], key=lambda item: item["name"])
        ],
        "public_top": [
            {
                key: item.get(key)
                for key in (
                    "reference",
                    "version",
                    "creator_name",
                    "description",
                    "download_count",
                    "install_count",
                    "parameters",
                )
            }
            for item in public_top
        ],
        "ranking_coverage": {
            key: ranking.get(key)
            for key in ("complete", "candidate_count", "inspected_count", "omitted_count", "errors")
        },
    }
    return stable_sha(snapshot)


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
    update_metadata: dict[str, dict[str, Any]] | None = None,
    update_metadata_errors: list[str] | None = None,
    update_metadata_omitted_count: int = 0,
    update_inspection_errors: list[str] | None = None,
    update_omitted_count: int = 0,
) -> dict[str, Any]:
    new, revised = classify_updates(grouped, start, end)
    inspected_updates = update_inspections or {}
    metadata_updates = update_metadata or {}
    for item in [*new, *revised]:
        base_reference = item["reference"]
        metadata = metadata_updates.get(base_reference)
        inspected = inspected_updates.get(base_reference)
        item["base_reference"] = base_reference
        item["actionable"] = inspected is not None
        if metadata is not None:
            item["description"] = metadata.get("description") or item["description"]
            item["creator_name"] = metadata.get("creator_name")
            item["creator_status"] = metadata.get("creator_status", "unavailable")
            item["version"] = metadata.get("version")
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
        "awareness_sha": awareness_fingerprint(organizations, grouped, public_top, ranking),
        "window": {
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
            "timezone": "UTC",
        },
        "sources": ["authorized_registry", "registry_flow_info", "play_inspect"],
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
                "creator_metadata": {
                    "status": (
                        "available"
                        if not update_metadata_errors and update_metadata_omitted_count == 0
                        else "partial"
                    ),
                    "omitted_count": update_metadata_omitted_count,
                    "errors": update_metadata_errors or [],
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
                "missing": [
                    "verified mapping from publication author to current identity",
                    "persistent verified receipts",
                ],
            },
            "run_metrics": {
                "status": "unavailable",
                "reason": (
                    "registry flow list/info expose lifetime download and install totals, "
                    "but no run count"
                ),
            },
        },
        "personal_stats": {
            "status": "unavailable",
            "reason": (
                "registry metadata can display publication authors, but cannot map them to the "
                "current identity or report verified run counts"
            ),
        },
        "next_checkpoint": next_checkpoint(end),
    }


def render_markdown(digest: dict[str, Any]) -> str:
    memory = digest.get("memory")
    if isinstance(memory, dict) and memory.get("status") == "unchanged":
        return "Nothing new since your last Play check."
    window = digest["window"]
    lines = [
        "# What’s new in Plays",
        "",
        f"Window: `{window['start']}` to `{window['end']}`",
    ]
    new_items = digest["org_updates"]["new"]
    revised_items = digest["org_updates"]["revised"]
    lines.extend(["", f"## Inbox ({len(new_items) + len(revised_items)})", ""])
    if not digest["org_updates"]["revised_complete"]:
        lines.append("Revisions are unavailable: registry list lacks released-version timestamps.")
        lines.append("")
    display_names = {org["slug"]: org["display_name"] for org in digest["organizations"]}
    all_updates = [*new_items, *revised_items]
    if not all_updates:
        lines.append(
            "— Your Play inbox is clear"
            if digest["org_updates"]["revised_complete"]
            else "— No new publications were found"
        )
    for owner in sorted({item["owner"] for item in all_updates}, key=lambda value: display_names.get(value, value).casefold()):
        owner_items = [item for item in all_updates if item["owner"] == owner]
        lines.extend([f"### {display_names.get(owner, owner)} (`{owner}`)", ""])
        for item in owner_items:
            creator = item.get("creator_name") or "Creator unavailable"
            description = " ".join((item.get("description") or "No description provided.").split())
            if len(description) > 180:
                description = description[:177].rstrip() + "…"
            state = "New" if item["kind"] == "new" else "Revised"
            lines.append(f"- **{item['name']}** · {state} · by {creator}")
            lines.append(f"  {description}")
            lines.append(
                f"  `{item['reference']}` · {item['visibility']} · {item['timestamp']}"
                + ("" if item.get("actionable") else " · inspect before Use")
            )
    ranking = digest["ranking"]
    lines.extend(["", f"## {ranking['label']} ({len(digest['public_top'])})", ""])
    lines.append(
        "Metric: lifetime downloads. Scope: authorized organizations; global public ranking "
        "and run counts are unavailable."
    )
    if not ranking["complete"]:
        lines.append("Coverage is partial because one or more public Plays could not be read.")
    lines.append("")
    if digest["public_top"]:
        for item in digest["public_top"]:
            creator = item.get("creator_name") or "Creator unavailable"
            description = " ".join((item.get("description") or "No description provided.").split())
            if len(description) > 180:
                description = description[:177].rstrip() + "…"
            lines.append(
                f"- **{item['name']}** · by {creator} · {item['owner']} · "
                f"{item['download_count']} downloads"
            )
            lines.append(f"  {description}")
            lines.append(f"  `{item['reference']}`")
    else:
        lines.append(f"— Unavailable: {ranking.get('reason', 'no eligible public Plays')}")
    stats = digest["personal_stats"]
    lines.extend(["", "## Your impact", "", f"— Unavailable: {stats['reason']}"])
    return "\n".join(lines)


def collect_digest(
    *,
    days: int = 1,
    since: str | None = None,
    checkpoint: Path | None = None,
    public_limit: int = 10,
    inspection_budget: int = 100,
    update_metadata_budget: int = 100,
    update_inspection_budget: int = 4,
    org_slugs: list[str] | None = None,
    organizations: list[Organization] | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Collect a digest without coupling callers to the CLI or output renderer."""

    if min(days, public_limit, inspection_budget, update_metadata_budget, update_inspection_budget) < 1:
        raise ValueError("digest limits and budgets must be at least 1")
    start, resolved_end = resolve_window(
        end=end or datetime.now(timezone.utc),
        days=days,
        since=since,
        checkpoint=checkpoint,
    )
    selected_orgs = org_slugs or []
    if organizations is not None and selected_orgs:
        raise ValueError("organizations and org_slugs are mutually exclusive")
    resolved_organizations = (
        organizations
        if organizations is not None
        else (
            [Organization(slug, slug) for slug in sorted(set(selected_orgs))]
            if selected_orgs
            else load_organizations()
        )
    )
    grouped = load_authorized_flows({org.slug for org in resolved_organizations})
    candidate_new, candidate_revised = classify_updates(grouped, start, resolved_end)
    update_references = [item["reference"] for item in [*candidate_new, *candidate_revised]]
    metadata_batch = load_registry_flow_infos(update_references, limit=update_metadata_budget)
    update_metadata = {flow["reference"]: flow for _, flow in metadata_batch.flows}
    update_batch = inspect_references(
        update_references,
        limit=update_inspection_budget,
    )
    update_inspections = {flow["reference"]: flow for _, flow in update_batch.flows}
    inspected: InspectionBatch = load_authorized_public_flow_infos(
        grouped,
        limit=inspection_budget,
    )
    return build_digest(
        resolved_organizations,
        grouped,
        inspected.flows,
        start=start,
        end=resolved_end,
        public_limit=public_limit,
        ranking_complete=not inspected.errors and inspected.omitted_count == 0,
        ranking_errors=inspected.errors,
        ranking_candidate_count=inspected.candidate_count,
        ranking_omitted_count=inspected.omitted_count,
        update_inspections=update_inspections,
        update_metadata=update_metadata,
        update_metadata_errors=metadata_batch.errors,
        update_metadata_omitted_count=metadata_batch.omitted_count,
        update_inspection_errors=update_batch.errors,
        update_omitted_count=update_batch.omitted_count,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--since", help="ISO-8601 start timestamp supplied by the host")
    parser.add_argument("--checkpoint", type=Path, help="read a host-persisted checkpoint token")
    parser.add_argument("--public-limit", type=int, default=10)
    parser.add_argument(
        "--inspection-budget",
        type=int,
        default=100,
        help="maximum authorized public Plays to read for ranking",
    )
    parser.add_argument(
        "--update-metadata-budget",
        type=int,
        default=100,
        help="maximum new or revised Plays to enrich with creator metadata",
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
    parser.add_argument(
        "--remember",
        action="store_true",
        help="compare with and advance Play's local on-demand digest memory",
    )
    parser.add_argument(
        "--state",
        type=Path,
        help="override the local digest memory path; implies --remember",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if (
        args.days < 1
        or args.public_limit < 1
        or args.inspection_budget < 1
        or args.update_metadata_budget < 1
        or args.update_inspection_budget < 1
    ):
        parser.error("digest limits and budgets must be at least 1")
    remember = args.remember or args.state is not None
    if remember and (args.since is not None or args.checkpoint is not None):
        parser.error("--remember/--state cannot be combined with --since or --checkpoint")
    state_path = args.state or DEFAULT_STATE_PATH
    remembered: tuple[str, dict[str, Any]] | None = None
    try:
        organizations = None
        since = args.since
        if remember:
            organizations = (
                [Organization(slug, slug) for slug in sorted(set(args.org))]
                if args.org
                else load_organizations()
            )
            scope = scope_contract(
                organizations,
                window_days=args.days,
                public_limit=args.public_limit,
                inspection_budget=args.inspection_budget,
                update_metadata_budget=args.update_metadata_budget,
                update_inspection_budget=args.update_inspection_budget,
            )
            key = scope_key(scope)
            previous = load_entry(state_path, key)
            if previous is not None and previous["scope"] != scope:
                raise DigestStateError(f"digest state entry {key} has a scope mismatch")
            if previous is not None:
                since = previous["checkpoint"]["last_seen_at"]
            remembered = (key, scope)
        digest = collect_digest(
            days=args.days,
            since=since,
            checkpoint=args.checkpoint,
            public_limit=args.public_limit,
            inspection_budget=args.inspection_budget,
            update_metadata_budget=args.update_metadata_budget,
            update_inspection_budget=args.update_inspection_budget,
            org_slugs=[] if organizations is not None else args.org,
            organizations=organizations,
        )
        if remember:
            digest["memory"] = {
                "schema": "play.digest-memory-result/v1",
                "scope_key": key,
                "status": compare_digest(digest, previous),
            }
    except (DigestStateError, RegistryReadError, TimeWindowError, ValueError) as error:
        print(f"play-digest: {error}", file=sys.stderr)
        return 1
    print(json_text(digest) if args.as_json else render_markdown(digest), flush=True)
    if remembered is not None:
        key, scope = remembered
        try:
            save_entry(state_path, key=key, scope=scope, digest=digest)
        except DigestStateError as error:
            print(f"play-digest: digest was shown but memory was not saved: {error}", file=sys.stderr)
            return 1
    return 0
