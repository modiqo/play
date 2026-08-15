"""Play awareness digest aggregation, comparison, and rendering."""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .digest_state import (
    default_state_path,
    DigestStateError,
    compare_digest,
    load_entry,
    save_entry,
    scope_contract,
    scope_key,
    stable_sha,
)
from .public_trends import fetch_authorized_public_stats
from .registry import (
    RegistryReadError,
    Organization,
    inspect_references,
    load_authorized_flows,
    load_registry_flow_infos,
    load_organizations,
)
from .render import json_text
from .timewindow import TimeWindowError, next_checkpoint, parse_timestamp, resolve_window


SCHEMA = "play.digest/v1"
DOMAIN_RECENT_LIMIT = 5
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


def _eligible_public(flows: list[tuple[str, dict]]) -> list[dict[str, Any]]:
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
        base_reference = flow.get("base_reference") or flow.get("reference") or f"{slug}/{flow['name']}"
        version = flow.get("version")
        exact_reference = flow.get("exact_reference") or (
            f"{base_reference}@{version}" if version else base_reference
        )
        eligible.append(
            {
                "reference": base_reference,
                "exact_reference": exact_reference,
                "base_reference": base_reference,
                "name": flow["name"],
                "owner": slug,
                "description": flow.get("description") or "",
                "creator_name": flow.get("creator_name"),
                "creator_status": flow.get("creator_status", "unavailable"),
                "owner_kind": flow.get("owner_kind", "unknown"),
                "visibility": "public",
                "version": flow.get("version"),
                "download_count": downloads,
                "install_count": flow.get("install_count"),
                "parameters": parameters if isinstance(parameters, dict) else {},
            }
        )
    eligible.sort(key=lambda item: (-item["download_count"], item["reference"]))
    return eligible


def rank_public(
    flows: list[tuple[str, dict]],
    limit: int,
    *,
    source_complete: bool = True,
    source_errors: list[str] | None = None,
    candidate_count: int | None = None,
    omitted_count: int = 0,
) -> tuple[list[dict], dict[str, Any]]:
    eligible = _eligible_public(flows)
    owner_counts: dict[str, int] = {}
    for item in eligible:
        owner_counts[item["owner"]] = owner_counts.get(item["owner"], 0) + 1
    ranking = {
        "metric": "lifetime_downloads",
        "label": (
            "Top public Plays by lifetime downloads in your organizations"
            if source_complete
            else "Top inspected public Plays by lifetime downloads in your organizations"
        ),
        "scope": "authorized_organizations",
        "eligible_count": len(eligible),
        "organization_count": len(owner_counts),
        "owner_counts": [
            {"owner": owner, "count": count}
            for owner, count in sorted(owner_counts.items())
        ],
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
    ranking_fetch_elapsed_ms: float | None = None,
    ranking_fetch_workers: int | None = None,
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
            item["reference"] = base_reference
            item["resolved_reference"] = inspected.get("exact_reference")
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
    ranking["fetch"] = {
        "mode": "parallel",
        "elapsed_ms": ranking_fetch_elapsed_ms,
        "workers": ranking_fetch_workers,
    }
    grouped_public: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in public_top:
        grouped_public.setdefault((item["owner"], item["owner_kind"]), []).append(item)
    all_public = _eligible_public(public_flows)
    registry_flows = {
        f"{owner}/{flow['name']}": flow
        for owner, flows in grouped.items()
        for flow in flows
    }
    for item in all_public:
        registry_flow = registry_flows.get(item["base_reference"])
        if registry_flow is None:
            item["recent_at"] = None
            item["recent_kind"] = None
            continue
        latest_version_created_at = registry_flow.get("latest_version_created_at")
        recent_at = latest_version_created_at or registry_flow.get("created_at")
        item["recent_at"] = recent_at if isinstance(recent_at, str) else None
        item["recent_kind"] = (
            "release" if isinstance(latest_version_created_at, str) else "publication"
        )
    domain_public: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in all_public:
        domain_public.setdefault((item["owner"], item["owner_kind"]), []).append(item)
    for plays in domain_public.values():
        plays.sort(key=lambda item: item["reference"])
        plays.sort(
            key=lambda item: (
                parse_timestamp(item["recent_at"], field=f"{item['reference']}.recent_at")
                if item.get("recent_at")
                else datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )
    display_names = {org.slug: org.display_name for org in organizations}
    public_domains = [
        {
            "owner": owner,
            "owner_kind": owner_kind,
            "display_name": display_names.get(owner, owner),
            "count": len(plays),
            "recent_play_limit": DOMAIN_RECENT_LIMIT,
            "plays": plays[:DOMAIN_RECENT_LIMIT],
        }
        for (owner, owner_kind), plays in domain_public.items()
    ]
    public_domains.sort(key=lambda domain: domain["owner"])
    public_domains.sort(
        key=lambda domain: (
            parse_timestamp(
                domain["plays"][0]["recent_at"],
                field=f"{domain['owner']}.recent_at",
            )
            if domain["plays"] and domain["plays"][0].get("recent_at")
            else datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
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
        "sources": [
            "authorized_registry",
            "public_play_card",
            "registry_flow_info",
            "play_inspect",
        ],
        "organizations": [
            {"slug": org.slug, "display_name": org.display_name} for org in organizations
        ],
        "org_updates": {
            "new": new,
            "revised": revised,
            "revised_complete": revision_complete,
        },
        "public_top": public_top,
        "public_groups": [
            {"owner": owner, "owner_kind": owner_kind, "plays": plays}
            for (owner, owner_kind), plays in sorted(grouped_public.items())
        ],
        "public_domains": public_domains,
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
                "stats_source": "public_play_card",
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
                    "registry Play list/info expose lifetime download and install totals, "
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
    window = digest["window"]
    new_items = digest["org_updates"]["new"]
    revised_items = digest["org_updates"]["revised"]
    ranking = digest["ranking"]
    public_count = ranking.get("eligible_count", 0)
    domains = digest.get("public_domains", [])
    domain_count = len(domains) if isinstance(domains, list) else 0
    coverage_prefix = "" if ranking.get("complete") is True else "at least "
    public_noun = "Play" if public_count == 1 else "Plays"
    organizations_only = isinstance(domains, list) and all(
        isinstance(domain, dict) and domain.get("owner_kind") == "org"
        for domain in domains
    )
    if organizations_only:
        domain_noun = "organization" if domain_count == 1 else "organizations"
    else:
        domain_noun = "publisher domain" if domain_count == 1 else "publisher domains"
    lines = []
    if isinstance(memory, dict) and memory.get("status") == "initial":
        lines.extend(
            [
                "**Nice—you’ve taken the first step. Play is connected, and you’re ready to use a reusable workflow.**",
                "",
            ]
        )
    lines.extend([
        "# What’s new in Plays",
        "",
        f"You can explore {coverage_prefix}**{public_count} runnable public {public_noun}** across **{domain_count} {domain_noun}** visible to you.",
        "",
    ])
    if isinstance(memory, dict) and memory.get("status") == "unchanged":
        lines.extend(["Nothing has changed since your last check; this is the current catalog.", ""])
    if isinstance(domains, list) and domains:
        lines.extend(["## Domains", ""])
        for domain in domains:
            if not isinstance(domain, dict):
                continue
            name = domain.get("display_name") or domain.get("owner") or "Unknown"
            count = domain.get("count", 0)
            noun = "Play" if count == 1 else "Plays"
            lines.append(f"- **{name}** — {count} {noun}")
        lines.append("")
    lines.extend(
        [
            "**Recommended first move: Run Hello.** It is a low-risk proof using public data, no account credentials, and no declared writes. Inspect acts like an X-ray: it shows the exact method and effects before you approve Rote to run it locally.",
            "",
            "Choose a domain for a short list, run Hello, or start with a useful outcome of your own.",
            "",
            f"Recent-publication window: `{window['start']}` → `{window['end']}` (UTC)",
            "",
        ]
    )
    if not digest["org_updates"]["revised_complete"]:
        lines.append(
            "Revisions are unavailable: registry list lacks released-version timestamps."
        )
        lines.append("")
    inbox_count = len(new_items) + len(revised_items)
    if inbox_count:
        lines.append(
            f"There {'is' if inbox_count == 1 else 'are'} **{inbox_count} new or revised "
            f"{'Play' if inbox_count == 1 else 'Plays'}** in this window. Choose a domain to see a short list."
        )
    elif digest["org_updates"]["revised_complete"]:
        lines.append("Your recent-publication inbox is clear.")
    else:
        lines.append("No new publications were found; revision coverage is unavailable.")
    lines.extend(["", "Counts cover runnable public cards visible through your authorized organizations; they are not a claim about the global registry."])
    if not ranking["complete"]:
        lines.append("Coverage is partial because one or more public Plays could not be read.")
    return "\n".join(lines)


def supports_domain_discovery(digest: object) -> bool:
    """Reject legacy v1 snapshots that predate organization/domain projection."""

    if not isinstance(digest, dict) or digest.get("schema") != SCHEMA:
        return False
    ranking = digest.get("ranking")
    domains = digest.get("public_domains")
    if not isinstance(ranking, dict) or not isinstance(domains, list):
        return False
    public_count = ranking.get("eligible_count")
    organization_count = ranking.get("organization_count")
    if (
        not isinstance(public_count, int)
        or isinstance(public_count, bool)
        or public_count < 0
        or not isinstance(organization_count, int)
        or isinstance(organization_count, bool)
        or organization_count < 0
        or organization_count != len(domains)
    ):
        return False
    projected_count = 0
    seen: set[str] = set()
    for domain in domains:
        if not isinstance(domain, dict):
            return False
        owner = domain.get("owner")
        count = domain.get("count")
        plays = domain.get("plays")
        if (
            not isinstance(owner, str)
            or not owner
            or owner in seen
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
            or not isinstance(plays, list)
        ):
            return False
        for play in plays:
            if not isinstance(play, dict):
                return False
            reference = play.get("reference")
            if (
                not isinstance(reference, str)
                or not reference
                or "@" in reference
                or reference.count("/") != 1
            ):
                return False
        seen.add(owner)
        projected_count += count
    return projected_count == public_count


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
    inspected = fetch_authorized_public_stats(
        grouped,
        limit=inspection_budget,
    )
    return build_digest(
        resolved_organizations,
        grouped,
        [(play["owner"], play) for play in inspected.plays],
        start=start,
        end=resolved_end,
        public_limit=public_limit,
        ranking_complete=not inspected.errors and inspected.omitted_count == 0,
        ranking_errors=inspected.errors,
        ranking_candidate_count=inspected.candidate_count,
        ranking_omitted_count=inspected.omitted_count,
        ranking_fetch_elapsed_ms=inspected.elapsed_ms,
        ranking_fetch_workers=inspected.workers,
        update_inspections=update_inspections,
        update_metadata=update_metadata,
        update_metadata_errors=metadata_batch.errors,
        update_metadata_omitted_count=metadata_batch.omitted_count,
        update_inspection_errors=update_batch.errors,
        update_omitted_count=update_batch.omitted_count,
    )


def _fresh_cached_digest(*, days: int, max_age_hours: float = 6.0) -> dict[str, Any] | None:
    """Serve the interactive digest from the background inbox cache when fresh.

    The what's-new surface tolerates the stale-while-revalidate window; a live
    registry sweep only runs when no fresh cache exists. Freshness comparison
    still runs against the remembered acknowledgment SHA, so "Nothing new since
    your last Play check" behaves identically from either source.
    """

    from .inbox_cache import read_cache  # local import: inbox_cache imports this module

    cache = read_cache()
    if cache is None or cache.get("window_days") != days:
        return None
    try:
        fetched = datetime.fromisoformat(str(cache.get("fetched_at")))
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    if age < 0 or age > max_age_hours * 3600:
        return None
    digest = cache.get("digest")
    if not supports_domain_discovery(digest):
        return None
    assert isinstance(digest, dict)
    return copy.deepcopy(digest)


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
    state_path = args.state or default_state_path()
    remembered: tuple[str, dict[str, Any]] | None = None
    key: str | None = None
    previous: dict[str, Any] | None = None
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
        digest = _fresh_cached_digest(days=args.days) if remember and not args.org else None
        served_from = "cache" if digest is not None else "live"
        if digest is None:
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
            assert key is not None
            digest["memory"] = {
                "schema": "play.digest-memory-result/v1",
                "scope_key": key,
                "status": compare_digest(digest, previous),
                "served_from": served_from,
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
