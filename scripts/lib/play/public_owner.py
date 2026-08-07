"""Resolve claimed and authorized Rote publication namespaces before save consent."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .render import json_text


SCHEMA = "play.public-owner-resolution/v1"
_HANDLE = re.compile(r"(?im)^handle:\s*([a-z0-9][a-z0-9_-]{0,62})\s*$")
_NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class PublicOwnerError(RuntimeError):
    """The local owner-resolution request itself was malformed."""


def _safe_text(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.replace("\x1b", "").split())[:80].strip()
    return cleaned or fallback


def _digest(*values: str) -> str:
    return hashlib.sha256("\n\0\n".join(values).encode()).hexdigest()


def _run(
    command: str,
    arguments: list[str],
    *,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            [command, *arguments],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(
            [command, *arguments],
            1,
            stdout="",
            stderr=f"probe unavailable: {type(error).__name__}",
        )


def _parse_orgs(stdout: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    organizations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not _NAMESPACE.fullmatch(slug) or slug in seen:
            continue
        seen.add(slug)
        display = _safe_text(item.get("display_name"), slug)
        organizations.append(
            {
                "id": f"org:{slug}",
                "owner": slug,
                "kind": "organization",
                "display_name": f"{display} ({slug})" if display != slug else slug,
                "ownership_description": (
                    f"Publish under the authorized organization namespace `{slug}`."
                ),
                "recommended": False,
            }
        )
    return organizations


def _summary(handle: str | None, organizations: list[dict[str, Any]]) -> str:
    if organizations:
        slugs = [f"`{item['owner']}`" for item in organizations[:3]]
        suffix = (
            f", plus {len(organizations) - 3} more"
            if len(organizations) > 3
            else ""
        )
        org_text = ", ".join(slugs) + suffix
    else:
        org_text = "none"
    if handle:
        return (
            "Public publication needs a namespace. "
            f"Your Rote profile handle `{handle}` is already claimed. "
            f"Authorized organizations: {org_text}."
        )
    if organizations:
        return (
            "Public publication needs a namespace. No Rote profile handle is claimed, but "
            f"authorized organizations are available: {org_text}. You can use one without "
            "attempting to claim a handle."
        )
    return (
        "Public publication needs a namespace, but no claimed profile handle or authorized "
        "organization is currently available."
    )


def resolve_public_owners(
    *,
    rote_command: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Return a bounded, credential-free namespace choice record from live Rote state."""

    started = time.perf_counter_ns()
    command = rote_command or shutil.which("rote")
    if not command:
        raise PublicOwnerError("Rote is not installed or not on PATH")
    if Path(command).name != "rote":
        raise PublicOwnerError("rote_command must resolve to a rote executable")

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="play-public-owner") as executor:
        identity_future = executor.submit(
            _run,
            command,
            ["registry", "whoami", "--verbose"],
            runner=runner,
        )
        organizations_future = executor.submit(
            _run,
            command,
            ["registry", "org", "list", "--json"],
            runner=runner,
        )
        identity = identity_future.result()
        organizations = organizations_future.result()
    evidence_ref = "sha256:" + _digest(
        identity.stdout,
        identity.stderr,
        organizations.stdout,
        organizations.stderr,
    )
    handle_match = _HANDLE.search(identity.stdout) if identity.returncode == 0 else None
    handle = handle_match.group(1) if handle_match else None
    org_choices = _parse_orgs(organizations.stdout) if organizations.returncode == 0 else []
    choices: list[dict[str, Any]] = []
    if handle:
        choices.append(
            {
                "id": f"profile:{handle}",
                "owner": handle,
                "kind": "profile_handle",
                "display_name": f"@{handle} (profile handle)",
                "ownership_description": (
                    f"Publish under the already-claimed public profile handle `{handle}`."
                ),
                "recommended": True,
            }
        )
    choices.extend(org_choices)

    probes_ok = identity.returncode == 0 and organizations.returncode == 0
    if not probes_ok:
        status = "unavailable"
        owner = None
        summary = (
            "Public namespace lookup is temporarily unavailable. Private save and Skip remain "
            "available; Public cannot proceed until the read-only profile and organization "
            "checks succeed."
        )
    elif not choices:
        status = "unavailable"
        owner = None
        summary = _summary(handle, org_choices)
    elif len(choices) == 1:
        status = "resolved"
        owner = choices[0]["owner"]
        summary = _summary(handle, org_choices)
    else:
        status = "choice_required"
        owner = None
        summary = _summary(handle, org_choices)

    return {
        "schema": SCHEMA,
        "ok": True,
        "publication": {
            "owner_resolution": status,
            "profile_handle": handle,
            "owner": owner,
            "owner_choices": choices,
            "owner_summary": summary,
            "owner_probe_ref": evidence_ref,
            "owner_probe_ns": time.perf_counter_ns() - started,
        },
    }


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rote-command")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(arguments)
    try:
        result = resolve_public_owners(rote_command=args.rote_command)
    except PublicOwnerError as error:
        print(f"play-public-owner: {error}", file=sys.stderr)
        return 1
    print(json_text(result) if args.json else result["publication"]["owner_summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
