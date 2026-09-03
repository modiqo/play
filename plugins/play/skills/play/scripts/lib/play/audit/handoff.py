"""Hand chosen findings to the skill that fixes them, and record what closed.

A handoff packet is a file, not an action: it lists the findings the author
chose, grouped by owner skill, each with its location, fix recipe, and
fixture. Play's controller passes the packet to rote-troubleshooting through
the existing delegated-action route. ``close`` re-audits afterwards and
writes the delta into the Play's history.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import store
from .runner import safe_audit


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _handoff_dir(reference: str) -> Path:
    return store._play_dir(reference) / "handoffs"  # noqa: SLF001 - same package, deliberate layout


def select(envelope: dict[str, Any], rule_ids: list[str] | None) -> list[dict[str, Any]]:
    items = list(envelope.get("facts") or []) + list(envelope.get("judgments") or [])
    if not rule_ids:
        return items
    wanted = set(rule_ids)
    return [item for item in items if item.get("id") in wanted]


def build_packet(envelope: dict[str, Any], findings: list[dict[str, Any]], *, chosen_by: str) -> dict[str, Any]:
    by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        by_owner[str(item.get("owner"))].append({
            "id": item.get("id"),
            "class": item.get("class"),
            "location": item.get("location"),
            "message": item.get("message"),
            "fix": item.get("fix"),
            "evidence": item.get("evidence"),
            "related_issue": item.get("related_issue"),
        })
    subject = envelope.get("subject") or {}
    return {
        "schema": "play-audit-handoff/1",
        "created_at": _now(),
        "chosen_by": chosen_by,
        "subject": {"reference": subject.get("reference"), "version": subject.get("version"),
                    "digest": subject.get("digest"), "path": subject.get("path")},
        "owners": {owner: items for owner, items in sorted(by_owner.items())},
        "count": len(findings),
        "instructions": (
            "Apply each fix at its location without changing the Play's declared contract. "
            "Route by owner: rote-flow-authoring for structure and deps.toml, rote-troubleshooting for "
            "failure contracts, rote-shell for command portability, rote-typescript-transformations for "
            "the presentation body, rote-registry for publication. When done, run "
            f"`play audit handoff {subject.get('reference')} --close` to record what closed."
        ),
    }


def render_packet(packet: dict[str, Any]) -> str:
    subject = packet["subject"]
    lines = [f"# Audit handoff: {subject.get('reference')}@{subject.get('version') or '?'}", "",
             f"Digest `{subject.get('digest')}`, {packet['count']} finding(s), chosen by {packet['chosen_by']}.", ""]
    for owner, items in packet["owners"].items():
        lines += [f"## {owner} ({len(items)})", ""]
        for item in items:
            loc = item.get("location") or {}
            where = loc.get("path") or (f"{loc.get('file')}:{loc.get('line')}" if loc.get("line") else loc.get("file") or "")
            lines.append(f"- **{item['id']}** `{where}`: {item['message']}")
            lines.append(f"  Fix: {item['fix']}")
        lines.append("")
    lines += ["## When done", "", packet["instructions"]]
    return "\n".join(lines)


def create(reference: str, root: Path, *, rule_ids: list[str] | None, chosen_by: str = "author") -> tuple[dict[str, Any], Path | None, str | None]:
    envelope = safe_audit(root, reference=reference, persist=True)
    if envelope.get("status") != "ok":
        return envelope, None, f"audit unavailable: {envelope.get('reason')}"
    findings = select(envelope, rule_ids)
    packet = build_packet(envelope, findings, chosen_by=chosen_by)
    directory = _handoff_dir(reference)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = _stamp()
        (directory / f"{stamp}.json").write_text(json.dumps({"packet": packet, "envelope": envelope}, indent=1))
        (directory / f"{stamp}.md").write_text(render_packet(packet))
        path: Path | None = directory / f"{stamp}.md"
    except OSError as error:
        return packet, None, f"could not write the handoff: {error}"
    store.append_history(reference, {
        "event": "handoff", "digest": envelope["subject"].get("digest"), "count": len(findings),
        "rules": sorted({str(item.get("id")) for item in findings}),
        "owners": sorted(packet["owners"]), "path": str(path), "at": packet["created_at"],
    })
    return packet, path, None


def latest_open(reference: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    directory = _handoff_dir(reference)
    if not directory.is_dir():
        return None, None
    candidates = sorted(directory.glob("*.json"))
    if not candidates:
        return None, None
    try:
        payload = json.loads(candidates[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None, None
    return payload.get("packet"), payload.get("envelope")


def close(reference: str, root: Path, *, run_ref: str | None = None) -> dict[str, Any]:
    packet, before = latest_open(reference)
    after = safe_audit(root, reference=reference, persist=True)
    delta = store.delta(before, after)
    entry = {
        "event": "handoff_closed", "at": _now(), "run_ref": run_ref,
        "handoff_created_at": (packet or {}).get("created_at"),
        **delta,
        "open_facts_after": (after.get("summary") or {}).get("open_facts"),
    }
    store.append_history(reference, entry)
    return {"delta": delta, "after": after.get("summary"), "handoff": (packet or {}).get("created_at")}


def render_delta(result: dict[str, Any]) -> str:
    delta = result["delta"]
    lines = [f"closed    {len(delta['closed'])}", f"remaining {len(delta['remaining'])}", f"new       {len(delta['new'])}"]
    for key in ("closed", "new"):
        for item in delta[key][:12]:
            lines.append(f"  {key:9s} {item}")
    lines.append(f"digest {str(delta.get('digest_before'))[:23]} → {str(delta.get('digest_after'))[:23]}")
    return "\n".join(lines)
