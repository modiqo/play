"""Authorized registry reads shared by inventory and digest surfaces."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .commands import CommandError, run_rote_json


class RegistryReadError(CommandError):
    pass


@dataclass(frozen=True)
class Organization:
    slug: str
    display_name: str


def load_organizations() -> list[Organization]:
    payload = run_rote_json("registry", "org", "list", "--json", error_type=RegistryReadError)
    if not isinstance(payload, list):
        raise RegistryReadError("organization list is not a JSON array")
    organizations: list[Organization] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
            raise RegistryReadError("organization list contains an invalid item")
        display_name = item.get("display_name")
        organizations.append(
            Organization(
                slug=item["slug"],
                display_name=display_name if isinstance(display_name, str) else item["slug"],
            )
        )
    return sorted(organizations, key=lambda org: (org.display_name.casefold(), org.slug.casefold()))


def _validate_flow(slug: str, flow: object) -> dict:
    if not isinstance(flow, dict) or not isinstance(flow.get("name"), str):
        raise RegistryReadError(f"Play list for {slug} contains an invalid item")
    visibility = flow.get("visibility")
    if visibility not in {"private", "public"}:
        raise RegistryReadError(f"Play {slug}/{flow['name']} has unknown visibility {visibility!r}")
    return flow


def load_authorized_flows(authorized_slugs: set[str]) -> dict[str, list[dict]]:
    payload = run_rote_json(
        "registry", "flow", "list", "--mine", "--json", error_type=RegistryReadError
    )
    if not isinstance(payload, list):
        raise RegistryReadError("Play list is not a JSON array")
    grouped = {slug: [] for slug in authorized_slugs}
    for item in payload:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise RegistryReadError("Play list contains an unsupported item shape")
        slug, flow = item
        if slug not in authorized_slugs:
            continue
        grouped[slug].append(_validate_flow(slug, flow))
    for flows in grouped.values():
        flows.sort(key=lambda flow: flow["name"].casefold())
    return grouped


def load_public_flows() -> list[tuple[str, dict]]:
    payload = run_rote_json("registry", "flow", "list", "--json", error_type=RegistryReadError)
    if not isinstance(payload, list):
        raise RegistryReadError("public Play list is not a JSON array")
    public: list[tuple[str, dict]] = []
    for item in payload:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise RegistryReadError("public Play list contains an unsupported item shape")
        slug, flow = item
        validated = _validate_flow(slug, flow)
        if validated["visibility"] == "public":
            public.append((slug, validated))
    return public


def member_count(slug: str) -> int:
    payload = run_rote_json(
        "registry", "org", "members", slug, "--json", error_type=RegistryReadError
    )
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RegistryReadError(f"member list for {slug} is not a JSON array of members")
    return len(payload)


def member_counts(organizations: list[Organization]) -> dict[str, int]:
    if not organizations:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(organizations))) as executor:
        counts = executor.map(member_count, [org.slug for org in organizations])
    return dict(zip((org.slug for org in organizations), counts, strict=True))
