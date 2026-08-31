"""Play awareness digest aggregation, comparison, and rendering."""

from __future__ import annotations

import argparse
import copy
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .digest_state import (
    authority_fingerprint,
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
    registry_failure_guidance,
    registry_failure_kind,
)
from .render import json_text
from .timewindow import TimeWindowError, next_checkpoint, parse_timestamp, resolve_window


SCHEMA = "play.digest/v1"
PUBLIC_SAMPLE_LIMIT = 10
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


def sample_public(
    flows: list[dict[str, Any]], *, limit: int = PUBLIC_SAMPLE_LIMIT
) -> list[dict[str, Any]]:
    """Return an unbiased display sample without changing catalog identity."""

    if limit < 1:
        raise ValueError("public sample limit must be at least 1")
    if not flows:
        return []
    return random.SystemRandom().sample(flows, min(limit, len(flows)))


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
    public_sample = sample_public(all_public)
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
        "public_sample": public_sample,
        "sample": {
            "strategy": "random",
            "limit": PUBLIC_SAMPLE_LIMIT,
            "available_count": len(all_public),
            "sampled_count": len(public_sample),
        },
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
    sample = digest.get("public_sample", [])
    sample_contract = digest.get("sample", {})
    availability = digest.get("availability")
    public_cache_only = (
        isinstance(availability, dict)
        and availability.get("status") == "public_cache_only"
    )
    coverage_prefix = (
        "" if ranking.get("complete") is True or public_cache_only else "at least "
    )
    public_noun = "Play" if public_count == 1 else "Plays"
    lines = []
    if isinstance(memory, dict) and memory.get("status") == "initial":
        lines.extend(
            [
                "**Nice—you’ve taken the first step. Play is connected, and you’re ready to use a reusable workflow.**",
                "",
            ]
        )
    lines.extend(["# What’s new in Plays", ""])
    if public_cache_only:
        assert isinstance(availability, dict)
        lines.extend(
            [
                "Live organization data is unavailable. Play is showing the last verified public Play "
                f"cache from `{availability.get('cache_fetched_at')}`.",
                "",
                "Private and organization-specific updates are unavailable. "
                f"{availability.get('guidance')}",
                "",
            ]
        )
    lines.extend(
        [
            f"You can explore {coverage_prefix}**{public_count} runnable public {public_noun}** visible to you.",
            "",
        ]
    )
    if isinstance(memory, dict) and memory.get("status") == "unchanged":
        lines.extend(["Nothing has changed since your last check; this is the current catalog.", ""])
    if isinstance(sample, list) and sample:
        sample_noun = "Play" if len(sample) == 1 else "Plays"
        lines.extend([f"## {len(sample)} {sample_noun} to explore", ""])
        for play in sample:
            if not isinstance(play, dict):
                continue
            name = play.get("name") or play.get("reference") or "Unknown"
            description = play.get("description") or "Inspect this Play."
            lines.append(f"- **{name}** — {description}")
        lines.append("")
    lines.extend(
        [
            "**Recommended first move: run Hello through Play.** Hello is a low-risk proof that uses public data, needs no account credentials, and declares no writes.",
            "",
            "**Use the form for your harness:**",
            "",
            "- **Codex:** `$play run hello`",
            "- **Claude Code, Cursor, Hermes, OpenCode, or DeepSeek Harness:** `/play run hello`",
            "- **Kimi Code:** `/skill:play run hello`",
            "- **Plain-language compatibility:** `play run hello`",
            "",
            "Each form activates Play. Play resolves qualified matches and asks which Play you want.",
            "It shows the exact method and effects before approval. Rote then runs it locally.",
            "",
            "- **Use your agent normally:** `run hello`.",
            "    Omit the Play prefix. Play stays out of the way. Your agent handles the request.",
            "",
            f"This is a random sample of {sample_contract.get('sampled_count', len(sample))} Plays from the current catalog. Choose one to inspect, search by outcome, or start with a useful outcome of your own.",
            "",
            f"Recent-publication window: `{window['start']}` → `{window['end']}` (UTC)",
            "",
        ]
    )
    if not public_cache_only and not digest["org_updates"]["revised_complete"]:
        lines.append(
            "Revisions are unavailable: registry list lacks released-version timestamps."
        )
        lines.append("")
    if not public_cache_only:
        inbox_count = len(new_items) + len(revised_items)
        if inbox_count:
            lines.append(
                f"There {'is' if inbox_count == 1 else 'are'} **{inbox_count} new or revised "
                f"{'Play' if inbox_count == 1 else 'Plays'}** in this window."
            )
        elif digest["org_updates"]["revised_complete"]:
            lines.append("Your recent-publication inbox is clear.")
        else:
            lines.append("No new publications were found; revision coverage is unavailable.")
    if public_cache_only:
        lines.extend(
            [
                "",
                "Counts come from the cached public catalog and may be stale. Play verifies every "
                "selected Play again before use.",
            ]
        )
    else:
        lines.extend(["", "Counts cover runnable public cards visible through your authorized organizations; they are not a claim about the global registry."])
    if not public_cache_only and not ranking["complete"]:
        lines.append("Coverage is partial because one or more public Plays could not be read.")
    return "\n".join(lines)


def supports_play_discovery(digest: object) -> bool:
    """Reject cached snapshots that predate direct randomized Play discovery."""

    if not isinstance(digest, dict) or digest.get("schema") != SCHEMA:
        return False
    ranking = digest.get("ranking")
    sample = digest.get("public_sample")
    sample_contract = digest.get("sample")
    if (
        not isinstance(ranking, dict)
        or not isinstance(sample, list)
        or not isinstance(sample_contract, dict)
    ):
        return False
    public_count = ranking.get("eligible_count")
    if (
        not isinstance(public_count, int)
        or isinstance(public_count, bool)
        or public_count < 0
        or sample_contract.get("strategy") != "random"
        or sample_contract.get("limit") != PUBLIC_SAMPLE_LIMIT
        or sample_contract.get("available_count") != public_count
        or sample_contract.get("sampled_count") != len(sample)
        or len(sample) > PUBLIC_SAMPLE_LIMIT
    ):
        return False
    seen: set[str] = set()
    for play in sample:
        if not isinstance(play, dict):
            return False
        reference = play.get("reference")
        if (
            not isinstance(reference, str)
            or not reference
            or reference in seen
            or "@" in reference
            or reference.count("/") != 1
        ):
            return False
        seen.add(reference)
    return len(sample) == min(PUBLIC_SAMPLE_LIMIT, public_count)


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
    grouped_flows: dict[str, list[dict]] | None = None,
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
    grouped = (
        grouped_flows
        if grouped_flows is not None
        else load_authorized_flows({org.slug for org in resolved_organizations})
    )
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


def _fresh_cached_digest(
    *,
    days: int,
    organizations: list[Organization],
    max_age_hours: float = 6.0,
) -> dict[str, Any] | None:
    """Serve the interactive digest from the background inbox cache when fresh.

    The what's-new surface tolerates the stale-while-revalidate window; a live
    registry sweep only runs when no fresh cache exists. Freshness comparison
    still runs against the remembered acknowledgment SHA, so "Nothing new since
    your last Play check" behaves identically from either source.
    """

    from .inbox_cache import read_cache  # local import: inbox_cache imports this module

    cache = read_cache()
    if (
        cache is None
        or cache.get("window_days") != days
        or cache.get("authority_sha256") != authority_fingerprint(organizations)
    ):
        return None
    try:
        fetched = datetime.fromisoformat(str(cache.get("fetched_at")))
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    if age < 0 or age > max_age_hours * 3600:
        return None
    digest = cache.get("digest")
    if supports_play_discovery(digest):
        assert isinstance(digest, dict)
        return copy.deepcopy(digest)
    return _upgrade_cached_discovery(digest, cache.get("catalog"))


def _cached_public_fallback(
    *, days: int, error: RegistryReadError
) -> dict[str, Any] | None:
    """Return public-only cached discovery when live organization scope is unknown."""

    from .inbox_cache import (  # local import: inbox_cache imports this module
        public_cache_entries,
        read_cache,
    )

    cache = read_cache()
    if (
        cache is None
        or cache.get("window_days") != days
        or cache.get("catalog_complete") is not True
        or not isinstance(cache.get("catalog_sha256"), str)
    ):
        return None
    try:
        fetched_at = parse_timestamp(cache.get("fetched_at"), field="cache.fetched_at")
    except TimeWindowError:
        return None
    cached_digest = cache.get("digest")
    public_catalog = public_cache_entries(cache)
    if not supports_play_discovery(cached_digest):
        return None
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in public_catalog:
        if not isinstance(entry, dict) or entry.get("visibility") != "public":
            return None
        reference = entry.get("reference")
        name = entry.get("name")
        if (
            not isinstance(reference, str)
            or reference.count("/") != 1
            or "@" in reference
            or reference in seen
            or not isinstance(name, str)
            or not name
        ):
            return None
        seen.add(reference)
        candidates.append(
            {
                "reference": reference,
                "base_reference": reference,
                "name": name,
                "description": str(entry.get("description") or ""),
                "parameters": {},
                "recent_at": entry.get("latest_version_created_at")
                or entry.get("created_at"),
                "recent_kind": (
                    "release" if entry.get("latest_version_created_at") else "publication"
                ),
            }
        )
    assert isinstance(cached_digest, dict)
    fallback = copy.deepcopy(cached_digest)
    public_sample = sample_public(candidates)
    owners = sorted({reference.split("/", 1)[0] for reference in seen})
    failure_kind = registry_failure_kind(error)
    ranking = dict(fallback["ranking"])
    ranking.update(
        {
            "label": "Public Plays from the last verified cache",
            "scope": "cached_public_catalog",
            "eligible_count": len(candidates),
            "organization_count": len(owners),
            "owner_counts": [
                {
                    "owner": owner,
                    "count": sum(
                        item["reference"].startswith(f"{owner}/")
                        for item in candidates
                    ),
                }
                for owner in owners
            ],
            "candidate_count": len(candidates),
            "inspected_count": len(candidates),
            "omitted_count": 0,
            "complete": False,
            "reason": "live registry unavailable; showing the last verified public cache",
        }
    )
    fallback.update(
        {
            "complete": False,
            "sources": ["verified_public_cache"],
            "organizations": [],
            "org_updates": {"new": [], "revised": [], "revised_complete": False},
            "public_top": [],
            "public_groups": [],
            "public_sample": public_sample,
            "sample": {
                "strategy": "random",
                "limit": PUBLIC_SAMPLE_LIMIT,
                "available_count": len(candidates),
                "sampled_count": len(public_sample),
            },
            "ranking": ranking,
            "availability": {
                "schema": "play.digest-availability/v1",
                "status": "public_cache_only",
                "reason": failure_kind,
                "guidance": registry_failure_guidance(error),
                "cache_fetched_at": fetched_at.isoformat(),
                "public_catalog": "cached",
                "organization_updates": "unavailable",
            },
            "memory": {
                "schema": "play.digest-memory-result/v1",
                "scope_key": None,
                "status": "degraded",
                "served_from": "public_cache",
            },
        }
    )
    capabilities = fallback.get("capabilities")
    if isinstance(capabilities, dict):
        capabilities["organization_updates"] = {
            "new": {"status": "unavailable", "reason": failure_kind},
            "revised": {"status": "unavailable", "reason": failure_kind},
            "actionable": {"status": "unavailable", "reason": failure_kind},
            "creator_metadata": {
                "status": "unavailable",
                "reason": failure_kind,
            },
        }
        capabilities["public_ranking"] = {
            "status": "cached",
            "scope": "cached_public_catalog",
            "stats_source": "verified_public_cache",
        }
    fallback["awareness_sha"] = stable_sha(
        {"public_catalog": candidates, "cache_fetched_at": fetched_at.isoformat()}
    )
    return fallback


def _upgrade_cached_discovery(
    digest: object, catalog: object
) -> dict[str, Any] | None:
    """Project a legacy fresh catalog into the current randomized sample contract.

    This is deliberately local-only. It lets an immediately invoked What's New
    request use an install-warmed catalog even when the prior cache predates the
    direct sample fields, instead of paying for a redundant registry sweep.
    """

    if not isinstance(digest, dict) or not isinstance(catalog, list):
        return None
    ranking = digest.get("ranking")
    if not isinstance(ranking, dict):
        return None
    expected_count = ranking.get("eligible_count")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool):
        return None
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in catalog:
        if not isinstance(entry, dict) or entry.get("visibility") != "public":
            continue
        reference = entry.get("reference")
        name = entry.get("name")
        if (
            not isinstance(reference, str)
            or reference.count("/") != 1
            or "@" in reference
            or reference in seen
            or not isinstance(name, str)
            or not name
        ):
            return None
        seen.add(reference)
        candidates.append(
            {
                "reference": reference,
                "base_reference": reference,
                "name": name,
                "description": str(entry.get("description") or ""),
                "parameters": {},
                "recent_at": entry.get("latest_version_created_at")
                or entry.get("created_at"),
                "recent_kind": (
                    "release" if entry.get("latest_version_created_at") else "publication"
                ),
            }
        )
    if len(candidates) != expected_count:
        return None
    upgraded = copy.deepcopy(digest)
    public_sample = sample_public(candidates)
    upgraded["public_sample"] = public_sample
    upgraded["sample"] = {
        "strategy": "random",
        "limit": PUBLIC_SAMPLE_LIMIT,
        "available_count": len(candidates),
        "sampled_count": len(public_sample),
    }
    return upgraded if supports_play_discovery(upgraded) else None


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
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
            if args.org:
                organizations = [
                    Organization(slug, slug) for slug in sorted(set(args.org))
                ]
            else:
                try:
                    organizations = load_organizations()
                except RegistryReadError as error:
                    fallback = _cached_public_fallback(days=args.days, error=error)
                    if fallback is None:
                        raise
                    print(
                        json_text(fallback) if args.as_json else render_markdown(fallback),
                        flush=True,
                    )
                    return 0
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
        digest = (
            _fresh_cached_digest(days=args.days, organizations=organizations)
            if remember and not args.org and organizations is not None
            else None
        )
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
    except RegistryReadError as error:
        print(f"play-digest: {registry_failure_guidance(error)}", file=sys.stderr)
        return 1
    except (DigestStateError, TimeWindowError, ValueError) as error:
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
