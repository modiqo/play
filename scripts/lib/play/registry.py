"""Authorized registry reads shared by inventory and digest surfaces."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .commands import CommandError, run_rote_json


class RegistryReadError(CommandError):
    pass


class PlayNotFoundError(RegistryReadError):
    pass


@dataclass(frozen=True)
class Organization:
    slug: str
    display_name: str
    id: str | None = None


@dataclass(frozen=True)
class InspectionBatch:
    flows: list[tuple[str, dict[str, Any]]]
    errors: list[str]
    candidate_count: int
    omitted_count: int


def load_organizations() -> list[Organization]:
    payload = run_rote_json("registry", "org", "list", "--json", error_type=RegistryReadError)
    if not isinstance(payload, list):
        raise RegistryReadError("organization list is not a JSON array")
    organizations: list[Organization] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
            raise RegistryReadError("organization list contains an invalid item")
        display_name = item.get("display_name")
        org_id = item.get("id")
        organizations.append(
            Organization(
                slug=item["slug"],
                display_name=display_name if isinstance(display_name, str) else item["slug"],
                id=org_id if isinstance(org_id, str) else None,
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


def _load_organization_flows(slug: str) -> tuple[str, list[dict]]:
    payload = run_rote_json(
        "registry", "flow", "list", "--org", slug, "--json", error_type=RegistryReadError
    )
    if not isinstance(payload, list):
        raise RegistryReadError(f"Play list for {slug} is not a JSON array")
    flows: list[dict] = []
    for item in payload:
        if isinstance(item, dict):
            flow = item
        elif (
            isinstance(item, list)
            and len(item) == 2
            and item[0] == slug
            and isinstance(item[1], dict)
        ):
            flow = item[1]
        else:
            raise RegistryReadError(f"Play list for {slug} contains an unsupported item shape")
        flows.append(_validate_flow(slug, flow))
    flows.sort(key=lambda flow: flow["name"].casefold())
    return slug, flows


def load_authorized_flows(authorized_slugs: set[str]) -> dict[str, list[dict]]:
    ordered = sorted(authorized_slugs)
    if not ordered:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(ordered))) as executor:
        loaded = executor.map(_load_organization_flows, ordered)
    return dict(loaded)


def _default_parameters(parameters: object) -> dict[str, Any]:
    if not isinstance(parameters, list):
        return {}
    defaults: dict[str, Any] = {}
    for parameter in parameters:
        if (
            isinstance(parameter, dict)
            and isinstance(parameter.get("name"), str)
            and "default" in parameter
        ):
            defaults[parameter["name"]] = parameter["default"]
    return defaults


def load_play_inspection(reference: str) -> dict[str, Any]:
    """Return the validated first-class ``rote play inspect`` payload."""
    try:
        payload = run_rote_json(
            "play", "inspect", reference, "--json", error_type=RegistryReadError
        )
    except RegistryReadError as error:
        if "play-not-found" in str(error):
            raise PlayNotFoundError("play not found") from error
        raise
    if isinstance(payload, dict) and payload.get("ok") is False:
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        error_type = (
            PlayNotFoundError
            if isinstance(error, dict) and error.get("kind") == "play-not-found"
            else RegistryReadError
        )
        raise error_type(message or f"Play inspect for {reference} failed")
    data = payload.get("data") if isinstance(payload, dict) and payload.get("ok") is True else None
    inspected = data.get("play_inspect") if isinstance(data, dict) else None
    if not isinstance(inspected, dict):
        raise RegistryReadError(f"Play inspect for {reference} has an unsupported shape")
    return inspected


def inspect_play(reference: str) -> dict[str, Any]:
    inspected = load_play_inspection(reference)
    identity = inspected.get("identity") if isinstance(inspected, dict) else None
    archive = inspected.get("archive") if isinstance(inspected, dict) else None
    execution = inspected.get("execution") if isinstance(inspected, dict) else None
    if not all(isinstance(item, dict) for item in (inspected, identity, archive, execution)):
        raise RegistryReadError(f"Play inspect for {reference} has an unsupported shape")
    owner = identity.get("owner")
    name = identity.get("name")
    visibility = identity.get("visibility")
    downloads = archive.get("download_count")
    installs = archive.get("install_count")
    if not isinstance(owner, str) or not isinstance(name, str):
        raise RegistryReadError(f"Play inspect for {reference} lacks canonical identity")
    if visibility not in {"private", "public"}:
        raise RegistryReadError(f"Play inspect for {reference} has invalid visibility")
    if not isinstance(downloads, int) or downloads < 0:
        raise RegistryReadError(f"Play inspect for {reference} lacks a valid download count")
    if not isinstance(installs, int) or installs < 0:
        raise RegistryReadError(f"Play inspect for {reference} lacks a valid install count")
    return {
        "reference": f"{owner}/{name}",
        "exact_reference": (
            f"{owner}/{name}@{identity['version']}"
            if isinstance(identity.get("version"), str) and identity["version"]
            else f"{owner}/{name}"
        ),
        "name": name,
        "owner": owner,
        "description": identity.get("description") or "",
        "visibility": visibility,
        "version": identity.get("version"),
        "download_count": downloads,
        "install_count": installs,
        "play_run_eligible": execution.get("play_run_eligible") is True,
        "default_parameters": _default_parameters(inspected.get("parameters")),
    }


def load_registry_flow_info(reference: str) -> dict[str, Any]:
    """Return display metadata and archive totals from ``registry flow info``.

    This read does not require Play execution authentication.  It is therefore
    suitable for awareness surfaces, but it deliberately does not imply that a
    Play is installed or runnable on the current machine.
    """

    owner, separator, requested_name = reference.partition("/")
    if not separator or not owner or not requested_name:
        raise RegistryReadError(f"invalid Play reference {reference!r}")
    payload = run_rote_json(
        "registry", "flow", "info", reference, "--json", error_type=RegistryReadError
    )
    skill = payload.get("skill") if isinstance(payload, dict) else None
    version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(skill, dict) or not isinstance(version, dict):
        raise RegistryReadError(f"Registry info for {reference} has an unsupported shape")
    name = skill.get("name")
    visibility = skill.get("visibility")
    release = version.get("version")
    downloads = version.get("download_count")
    installs = version.get("install_count")
    if name != requested_name:
        raise RegistryReadError(f"Registry info for {reference} resolved {name!r} instead")
    if visibility not in {"private", "public"}:
        raise RegistryReadError(f"Registry info for {reference} has invalid visibility")
    if not isinstance(release, str) or not release:
        raise RegistryReadError(f"Registry info for {reference} lacks a released version")
    if not isinstance(downloads, int) or downloads < 0:
        raise RegistryReadError(f"Registry info for {reference} lacks a valid download count")
    if not isinstance(installs, int) or installs < 0:
        raise RegistryReadError(f"Registry info for {reference} lacks a valid install count")

    metadata = version.get("metadata")
    provenance = metadata.get("provenance") if isinstance(metadata, dict) else None
    author = provenance.get("author") if isinstance(provenance, dict) else None
    creator_name = author.strip() if isinstance(author, str) and author.strip() else None
    return {
        "reference": reference,
        "exact_reference": f"{reference}@{release}",
        "name": name,
        "owner": owner,
        "description": skill.get("description") or "",
        "visibility": visibility,
        "version": release,
        "version_created_at": version.get("created_at"),
        "status": version.get("status"),
        "download_count": downloads,
        "install_count": installs,
        "creator_name": creator_name,
        "creator_status": "available" if creator_name else "unavailable",
        "creator_source": "version.metadata.provenance.author" if creator_name else None,
        "default_parameters": {},
    }


def load_registry_flow_infos(
    requested_references: list[str],
    *,
    limit: int = 100,
    require_public: bool = False,
) -> InspectionBatch:
    """Load bounded registry display metadata for a set of canonical references."""

    if limit < 1:
        raise RegistryReadError("registry info limit must be at least 1")
    references = list(dict.fromkeys(requested_references))
    candidate_count = len(references)
    selected = references[:limit]
    omitted_count = candidate_count - len(selected)
    if not selected:
        return InspectionBatch([], [], candidate_count, omitted_count)

    def load(reference: str) -> tuple[str, dict[str, Any] | None, str | None]:
        try:
            flow = load_registry_flow_info(reference)
        except RegistryReadError as error:
            return reference, None, str(error)
        if require_public and flow["visibility"] != "public":
            return reference, None, "registry info no longer reports public visibility"
        return reference, flow, None

    with ThreadPoolExecutor(max_workers=min(8, len(selected))) as executor:
        loaded = list(executor.map(load, selected))
    flows = [(flow["owner"], flow) for _, flow, error in loaded if flow is not None and error is None]
    errors = [f"{reference}: {error}" for reference, _, error in loaded if error is not None]
    return InspectionBatch(flows, errors, candidate_count, omitted_count)


def inspect_references(
    requested_references: list[str],
    *,
    limit: int = 8,
    require_public: bool = False,
) -> InspectionBatch:
    if limit < 1:
        raise RegistryReadError("inspection limit must be at least 1")
    references = list(dict.fromkeys(requested_references))
    candidate_count = len(references)
    selected = references[:limit]
    omitted_count = candidate_count - len(selected)
    if not selected:
        return InspectionBatch([], [], candidate_count, omitted_count)

    def inspect(reference: str) -> tuple[str, dict[str, Any] | None, str | None]:
        try:
            flow = inspect_play(reference)
        except RegistryReadError as error:
            return reference, None, str(error)
        if flow["reference"] != reference:
            return reference, None, f"inspect resolved {flow['reference']} instead"
        if require_public and flow["visibility"] != "public":
            return reference, None, "inspect no longer reports public visibility"
        return reference, flow, None

    with ThreadPoolExecutor(max_workers=min(8, len(selected))) as executor:
        inspected = list(executor.map(inspect, selected))
    flows = [(flow["owner"], flow) for _, flow, error in inspected if flow is not None and error is None]
    errors = [f"{reference}: {error}" for reference, _, error in inspected if error is not None]
    return InspectionBatch(flows, errors, candidate_count, omitted_count)


def inspect_authorized_public_flows(
    grouped: dict[str, list[dict]],
    *,
    limit: int = 8,
) -> InspectionBatch:
    candidates = [
        (
            f"{slug}/{flow['name']}",
            flow.get("updated_at") or flow.get("created_at") or "",
        )
        for slug, flows in grouped.items()
        for flow in flows
        if flow["visibility"] == "public" and not flow.get("deleted_at")
    ]
    candidates.sort(key=lambda item: item[0])
    candidates.sort(key=lambda item: item[1], reverse=True)
    return inspect_references(
        [reference for reference, _ in candidates],
        limit=limit,
        require_public=True,
    )


def load_authorized_public_flow_infos(
    grouped: dict[str, list[dict]],
    *,
    limit: int = 100,
) -> InspectionBatch:
    """Load ranking metadata for authorized public Plays without execution checks."""

    candidates = sorted(
        f"{slug}/{flow['name']}"
        for slug, flows in grouped.items()
        for flow in flows
        if flow["visibility"] == "public" and not flow.get("deleted_at")
    )
    return load_registry_flow_infos(candidates, limit=limit, require_public=True)


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
