"""Render authorized organization and registry Play inventories without persistence."""

from __future__ import annotations

import argparse
import sys

from .registry import (
    Organization,
    RegistryReadError,
    load_authorized_flows,
    load_organizations,
    member_counts,
)
from .render import join_sections


InventoryError = RegistryReadError


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def organization_label(org: Organization) -> str:
    if org.display_name == org.slug:
        return org.slug
    return f"{org.display_name} (`{org.slug}`)"


def render_organizations(
    organizations: list[Organization], flows: dict[str, list[dict]], members: dict[str, int]
) -> str:
    lines = [
        "# Organizations",
        "",
        "| Organization | Members | Private | Public | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for org in organizations:
        private = sum(flow["visibility"] == "private" for flow in flows[org.slug])
        public = sum(flow["visibility"] == "public" for flow in flows[org.slug])
        lines.append(
            f"| {escape_cell(organization_label(org))} | {members[org.slug]} | "
            f"{private} | {public} | {private + public} |"
        )
    if not organizations:
        lines.append("| — None | 0 | 0 | 0 | 0 |")
    return "\n".join(lines)


def render_plays(organizations: list[Organization], flows: dict[str, list[dict]]) -> str:
    lines = ["# Plays by organization"]
    if not organizations:
        return "\n".join([*lines, "", "— None"])
    for org in organizations:
        org_flows = flows[org.slug]
        lines.extend(["", f"## {organization_label(org)} — {len(org_flows)}"])
        for visibility in ("private", "public"):
            visible = [flow for flow in org_flows if flow["visibility"] == visibility]
            lines.extend(["", f"### {visibility.title()} ({len(visible)})", ""])
            if visible:
                lines.extend(f"- `{flow['name']}`" for flow in visible)
            else:
                lines.append("— None")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", choices=("orgs", "plays", "all"))
    args = parser.parse_args()
    try:
        organizations = load_organizations()
        flows = load_authorized_flows({org.slug for org in organizations})
        sections = []
        if args.view in {"orgs", "all"}:
            sections.append(render_organizations(organizations, flows, member_counts(organizations)))
        if args.view in {"plays", "all"}:
            sections.append(render_plays(organizations, flows))
    except InventoryError as error:
        print(f"play-inventory: {error}", file=sys.stderr)
        return 1
    print(join_sections(sections))
    return 0
