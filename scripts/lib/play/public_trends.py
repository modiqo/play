"""Parallel public Play statistics for awareness and integration surfaces."""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any
from urllib.parse import quote

from .commands import CommandError, run_json
from .registry import Organization, load_authorized_flows, load_organizations
from .render import json_text


SCHEMA = "play.public-trends/v1"
PUBLIC_CARD_SCHEMA = "rote.play.v1"
_REFERENCE = re.compile(
    r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9_-]*)/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)"
    r"(?:@(?P<version>[A-Za-z0-9][A-Za-z0-9.+_-]*))?$"
)


class PublicStatsError(CommandError):
    """A public Play card could not supply trustworthy counters."""


@dataclass(frozen=True)
class PublicStatsBatch:
    plays: list[dict[str, Any]]
    errors: list[str]
    candidate_count: int
    omitted_count: int
    elapsed_ms: float
    workers: int


def _reference_parts(reference: str) -> tuple[str, str]:
    match = _REFERENCE.fullmatch(reference)
    if match is None:
        raise PublicStatsError(f"invalid public Play reference {reference!r}")
    return match.group("owner"), match.group("name")


def _card_url(reference: str) -> str:
    _reference_parts(reference)
    return f"https://play.modiqo.ai/{quote(reference, safe='/@._-')}.json"


def fetch_public_stats(reference: str) -> dict[str, Any]:
    """Fetch one public card without redirects, cookies, or credentials."""

    requested_owner, requested_name = _reference_parts(reference)
    started = perf_counter_ns()
    payload = run_json(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--max-redirs",
            "0",
            "--header",
            "Accept: application/json",
            _card_url(reference),
        ],
        error_type=PublicStatsError,
    )
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    if not isinstance(payload, dict) or payload.get("schema") != PUBLIC_CARD_SCHEMA:
        raise PublicStatsError(f"public card for {reference} has an unsupported shape")
    if payload.get("visibility") != "public":
        raise PublicStatsError(f"public card for {reference} is not public")
    owner = payload.get("owner")
    stats = payload.get("stats")
    resolved_reference = payload.get("reference")
    if not isinstance(owner, dict) or owner.get("slug") != requested_owner:
        raise PublicStatsError(f"public card for {reference} resolved a different owner")
    if not isinstance(resolved_reference, str):
        raise PublicStatsError(f"public card for {reference} lacks a canonical reference")
    resolved_owner, resolved_name = _reference_parts(resolved_reference)
    if (resolved_owner, resolved_name) != (requested_owner, requested_name):
        raise PublicStatsError(f"public card for {reference} resolved {resolved_reference!r}")
    if "@" in reference and resolved_reference != reference:
        raise PublicStatsError(f"public card for {reference} resolved {resolved_reference!r}")
    if not isinstance(stats, dict):
        raise PublicStatsError(f"public card for {reference} does not expose stats")
    downloads = stats.get("downloads")
    installs = stats.get("installs")
    if not isinstance(downloads, int) or isinstance(downloads, bool) or downloads < 0:
        raise PublicStatsError(f"public card for {reference} has an invalid download count")
    if not isinstance(installs, int) or isinstance(installs, bool) or installs < 0:
        raise PublicStatsError(f"public card for {reference} has an invalid install count")
    version = payload.get("version")
    return {
        "reference": resolved_reference,
        "exact_reference": resolved_reference,
        "base_reference": f"{resolved_owner}/{resolved_name}",
        "name": resolved_name,
        "owner": resolved_owner,
        "owner_kind": owner.get("kind") if owner.get("kind") in {"org", "user"} else "unknown",
        "title": payload.get("title") if isinstance(payload.get("title"), str) else resolved_name,
        "description": payload.get("description") if isinstance(payload.get("description"), str) else "",
        "visibility": "public",
        "version": version if isinstance(version, str) else None,
        "download_count": downloads,
        "install_count": installs,
        "default_parameters": {},
        "stats_source": _card_url(reference),
        "fetch_latency_ms": round(elapsed_ms, 3),
    }


def fetch_public_stats_parallel(
    requested_references: list[str],
    *,
    limit: int = 100,
    max_workers: int = 8,
) -> PublicStatsBatch:
    """Fetch a bounded set of public counters concurrently and deterministically."""

    if limit < 1:
        raise PublicStatsError("public stats limit must be at least 1")
    if max_workers < 1:
        raise PublicStatsError("public stats workers must be at least 1")
    references = list(dict.fromkeys(requested_references))
    candidate_count = len(references)
    selected = references[:limit]
    omitted_count = candidate_count - len(selected)
    workers = min(max_workers, len(selected)) if selected else 0
    if not selected:
        return PublicStatsBatch([], [], candidate_count, omitted_count, 0.0, workers)

    started = perf_counter_ns()
    plays: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="play-public-stats") as executor:
        futures = {executor.submit(fetch_public_stats, reference): reference for reference in selected}
        for future in as_completed(futures):
            reference = futures[future]
            try:
                plays.append(future.result())
            except PublicStatsError as error:
                errors.append(f"{reference}: {error}")
    plays.sort(key=lambda item: item["base_reference"])
    errors.sort()
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    return PublicStatsBatch(
        plays,
        errors,
        candidate_count,
        omitted_count,
        round(elapsed_ms, 3),
        workers,
    )


def authorized_public_references(grouped: dict[str, list[dict[str, Any]]]) -> list[str]:
    return sorted(
        f"{owner}/{play['name']}"
        for owner, plays in grouped.items()
        for play in plays
        if play.get("visibility") == "public" and not play.get("deleted_at")
    )


def fetch_authorized_public_stats(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    limit: int = 100,
    max_workers: int = 8,
) -> PublicStatsBatch:
    return fetch_public_stats_parallel(
        authorized_public_references(grouped),
        limit=limit,
        max_workers=max_workers,
    )


def build_public_trends(batch: PublicStatsBatch, *, top: int = 10) -> dict[str, Any]:
    """Build the reusable grouped snapshot; do not claim lifetime totals are a trend."""

    if top < 1:
        raise PublicStatsError("public trends top limit must be at least 1")
    ranked = sorted(
        batch.plays,
        key=lambda item: (-item["download_count"], -item["install_count"], item["reference"]),
    )[:top]
    owners: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for play in ranked:
        owners.setdefault((play["owner"], play["owner_kind"]), []).append(play)
    groups = [
        {"owner": owner, "owner_kind": owner_kind, "plays": plays}
        for (owner, owner_kind), plays in sorted(owners.items())
    ]
    return {
        "schema": SCHEMA,
        "complete": not batch.errors and batch.omitted_count == 0,
        "metric": "lifetime_downloads",
        "metric_kind": "cumulative_snapshot",
        "trend_status": "unavailable",
        "trend_reason": "windowed download and install changes require two dated snapshots",
        "scope": "authorized_organizations",
        "candidate_count": batch.candidate_count,
        "fetched_count": len(batch.plays),
        "omitted_count": batch.omitted_count,
        "errors": batch.errors,
        "fetch": {
            "mode": "parallel",
            "workers": batch.workers,
            "elapsed_ms": batch.elapsed_ms,
        },
        "groups": groups,
        "ranked": ranked,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Public Play activity",
        "",
        "Lifetime downloads and installs in your authorized organizations. "
        "These totals are not a time-window trend.",
    ]
    if not report["complete"]:
        lines.extend(["", "Coverage is partial because some public cards could not be read."])
    for group in report["groups"]:
        lines.extend(["", f"## {group['owner']} ({group['owner_kind']})", ""])
        for play in group["plays"]:
            lines.append(
                f"- **{play['title']}** · {play['download_count']} downloads · "
                f"{play['install_count']} installs"
            )
            lines.append(f"  `{play['reference']}`")
    if not report["groups"]:
        lines.extend(["", "— No public Plays with available statistics were found."])
    fetch = report["fetch"]
    lines.extend(
        [
            "",
            f"Fetched {report['fetched_count']} of {report['candidate_count']} public cards "
            f"in {fetch['elapsed_ms']:.3f} ms with {fetch['workers']} workers.",
        ]
    )
    return "\n".join(lines)


def collect_public_trends(
    *,
    references: list[str] | None = None,
    org_slugs: list[str] | None = None,
    limit: int = 100,
    top: int = 10,
    max_workers: int = 8,
) -> dict[str, Any]:
    if references:
        batch = fetch_public_stats_parallel(references, limit=limit, max_workers=max_workers)
    else:
        selected_orgs = sorted(set(org_slugs or []))
        organizations = (
            [Organization(slug, slug) for slug in selected_orgs]
            if selected_orgs
            else load_organizations()
        )
        grouped = load_authorized_flows({org.slug for org in organizations})
        batch = fetch_authorized_public_stats(grouped, limit=limit, max_workers=max_workers)
    return build_public_trends(batch, top=top)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--play", action="append", default=[], help="public owner/name reference")
    parser.add_argument("--org", action="append", default=[], help="authorized owner namespace")
    parser.add_argument("--limit", type=int, default=100, help="maximum public cards to fetch")
    parser.add_argument("--top", type=int, default=10, help="maximum ranked Plays to show")
    parser.add_argument("--workers", type=int, default=8, help="maximum concurrent card fetches")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.play and args.org:
        parser.error("--play and --org are mutually exclusive")
    try:
        report = collect_public_trends(
            references=args.play,
            org_slugs=args.org,
            limit=args.limit,
            top=args.top,
            max_workers=args.workers,
        )
    except (PublicStatsError, CommandError, ValueError) as error:
        print(f"play-public-trends: {error}", file=sys.stderr)
        return 1
    print(json_text(report) if args.as_json else render_markdown(report))
    return 0
