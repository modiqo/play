"""The human renderings of one envelope.

``card``    consumer: a map of the Play, facts only, no rule ids, no counts.
``author``  author: a work order; every finding with its owner and fix.
``report``  author to registry inbox: Markdown with the digest.
``history`` one line per stored audit.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

_KIND_LABEL = {"process": "runs a local command", "adapter": "calls a service", "browser": "drives a browser"}

# One plain sentence per fact class that a consumer should expect to see happen.
_EXPECTATIONS: dict[str, str] = {
    "FANOUT_OVER_PREVIEW": "Very large intermediate lists are cut at 64 KiB; the full text is kept in the run's artifacts.",
    "ADAPTER_SOURCE_PROVENANCE_DIFFERS": "The service adapter installed here comes from a different publisher than this Play expects; rote may ask you to reinstall it.",
    "ABSOLUTE_HOME_PATH": "A path inside the Play points at its author's home folder and may not exist here.",
    "BODY_STRANDED": "Part of this Play's code is never executed; the result comes only from its declared steps.",
}

_OWNER_HINT = {
    "rote-flow-authoring": "structure, parameters, deps.toml, resources",
    "rote-troubleshooting": "failure contract and partial results",
    "rote-shell": "shell and command portability",
    "rote-typescript-transformations": "presentation body",
    "rote-registry": "publication and adapters",
}


def _pad(rows: list[list[str]], indent: str = "  ") -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    widths = [max(len(row[i]) for row in rows) for i in range(width)]
    return [indent + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]


def _first_sentence(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    end = text.find(". ")
    sentence = text[: end + 1] if 0 < end < limit else text
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _title(envelope: dict[str, Any]) -> str:
    subject = envelope.get("subject") or {}
    reference = str(subject.get("reference") or "")
    if subject.get("version"):
        reference += f"@{subject['version']}"
    return reference


def _where(item: dict[str, Any]) -> str:
    loc = item.get("location") or {}
    if loc.get("path"):
        return str(loc["path"])
    if loc.get("line"):
        return f"{loc.get('file')}:{loc.get('line')}"
    return str(loc.get("file") or "package")


def _status_words(need: dict[str, Any]) -> str:
    status = need.get("status")
    found = need.get("found")
    if status == "present":
        return f"present   {found or need.get('path') or ''}".rstrip()
    if status == "version_unverified":
        return f"present   {found or ''} (version not checked)".rstrip()
    if status == "version_low":
        return f"too old   {found} here, needs {need.get('declared')}"
    if status == "profile_absent":
        return "not shipped on this profile"
    return "missing"


def card(envelope: dict[str, Any]) -> str:
    if envelope.get("status") != "ok":
        return ""
    subject = envelope.get("subject") or {}
    lines: list[str] = [_title(envelope)]
    if subject.get("description"):
        lines.append(f"  {_first_sentence(str(subject['description']))}")
    if subject.get("source") == "pulled":
        lines.append("  Pulled into a temporary folder for this look; nothing was installed.")

    shape = envelope.get("shape") or []
    if shape:
        lines += ["", "What it does, in order"]
        rows = []
        for index, step in enumerate(shape, 1):
            label = step.get("label") or _KIND_LABEL.get(step.get("kind"), step.get("kind") or "step")
            detail = ", ".join(step.get("commands") or []) or str(step.get("endpoint") or "").replace("adapter/", "")
            if step.get("unread_body"):
                detail = (detail + ", " if detail else "") + "code this inspection could not read"
            extra = "repeated per item" if step.get("fan_out") else ""
            rows.append([f"{index}.", str(step.get("name")), label, detail, extra])
        lines += _pad(rows)

    reach = envelope.get("reach") or {}
    lines += ["", "What it touches"]
    services = reach.get("services") or []
    signin = reach.get("services_requiring_signin") or []
    service_text = ", ".join(
        s.replace("adapter/", "") + (" (needs sign-in)" if s in signin else "") for s in services
    ) or "no services"
    inputs = reach.get("parameters") or []
    rows = [
        ["Runs here", ", ".join(reach.get("commands") or []) or "no local commands"],
        ["Calls", service_text],
        ["Inputs you supply", ", ".join(inputs) if inputs else "none"],
        ["Writes", ", ".join(reach.get("writes") or []) or "nothing declared"],
    ]
    lines += _pad(rows)

    host = envelope.get("host") or {}
    needs = host.get("needs") or []
    if needs:
        heading = "On this machine" if host.get("profile") == "live" else f"On {host.get('label')}"
        lines += ["", heading]
        lines += _pad([[n["name"], _status_words(n)] for n in needs])

    # Facts only. Judgments never reach the card, by contract.
    expectations: list[str] = []
    for item in envelope.get("facts") or []:
        sentence = _EXPECTATIONS.get(str(item.get("id")))
        if sentence and sentence not in expectations:
            expectations.append(sentence)
    if expectations:
        lines += ["", "Good to know"]
        lines += [f"  {s}" for s in expectations[:3]]

    unread = reach.get("unread_bodies") or []
    skipped = [u for u in envelope.get("unknowns") or [] if u.get("kind") in {"RULES_SKIPPED", "EXTRACTOR_FAILED", "VERSION_DIFFERS"}]
    if unread or skipped:
        lines += ["", "Not inspected"]
        for name in unread:
            lines.append(f"  step {name} runs code this inspection could not read")
        for item in skipped:
            lines.append(f"  {item.get('reason')}")

    summary = envelope.get("summary") or {}
    verdict = "yes" if summary.get("can_run_here") else f"not yet: {summary.get('cannot_run_reason')}"
    lines += ["", f"Can it run here?  {verdict}"]
    return "\n".join(lines)


def author(envelope: dict[str, Any]) -> str:
    if envelope.get("status") != "ok":
        return f"audit unavailable: {envelope.get('reason')}"
    subject = envelope.get("subject") or {}
    summary = envelope.get("summary") or {}
    facts = envelope.get("facts") or []
    judgments = envelope.get("judgments") or []
    unknowns = envelope.get("unknowns") or []
    suppressed = envelope.get("suppressions") or []

    lines = [_title(envelope)]
    meta = [f"digest {str(subject.get('digest'))[:23]}"]
    if subject.get("audited_at"):
        meta.append(f"audited {subject['audited_at']}")
    if subject.get("elapsed_ms") is not None:
        meta.append(f"{subject['elapsed_ms']} ms")
    if subject.get("source") == "pulled":
        meta.append("pulled to a temporary folder")
    lines.append("  " + " · ".join(meta))

    if not facts and not judgments and not unknowns:
        lines += ["", "Clean. No facts, no judgments, nothing left unread."]
    else:
        parts = [f"{len(facts)} fact{'s' if len(facts) != 1 else ''}", f"{len(judgments)} judgment{'s' if len(judgments) != 1 else ''}"]
        if unknowns:
            parts.append(f"{len(unknowns)} unknown{'s' if len(unknowns) != 1 else ''}")
        if suppressed:
            parts.append(f"{len(suppressed)} suppressed")
        lines += ["", "  " + ", ".join(parts)]

    shape = envelope.get("shape") or []
    if shape:
        lines += ["", "Steps"]
        rows = []
        touched: dict[str, list[str]] = defaultdict(list)
        for item in facts + judgments:
            path = str((item.get("location") or {}).get("path") or "")
            if path.startswith("steps."):
                touched[path.split(".", 1)[1]].append(str(item["id"]))
        for step in shape:
            name = str(step.get("name"))
            detail = ", ".join(step.get("commands") or []) or str(step.get("endpoint") or "")
            rows.append([name, step.get("kind") or "", detail, ", ".join(sorted(set(touched.get(name, []))))])
        lines += _pad(rows)

    for heading, items in (("Facts", facts), ("Judgments", judgments)):
        if not items:
            continue
        lines += ["", f"{heading} ({len(items)})"]
        for item in items:
            precision = f"  precision {item['precision']:.0%}" if item.get("precision") is not None else ""
            lines.append(f"  {item['id']}  {_where(item)}{precision}")
            lines.append(f"      {item['message']}")
            lines.append(f"      fix   {item['fix']}")
            lines.append(f"      owner {item['owner']}")
            if item.get("related_issue"):
                lines.append(f"      see   {item['related_issue']}")

    if suppressed:
        lines += ["", f"Suppressed by the author ({len(suppressed)})"]
        for item in suppressed:
            lines.append(f"  {item['id']}  {item.get('suppressed_reason')}")

    if unknowns:
        lines += ["", f"Not inspected ({len(unknowns)})"]
        for item in unknowns:
            lines.append(f"  {item['kind']}  {item['subject']}")
            lines.append(f"      {item['reason']}")

    host = envelope.get("host") or {}
    needs = host.get("needs") or []
    if needs:
        lines += ["", f"Host: {host.get('label')}"]
        lines += _pad([[n["name"], _status_words(n)] for n in needs])

    if facts or judgments:
        owners: dict[str, list[str]] = defaultdict(list)
        for item in facts + judgments:
            owners[str(item["owner"])].append(str(item["id"]))
        lines += ["", "Next"]
        for owner, rule_ids in sorted(owners.items()):
            lines.append(f"  {owner:<32} {len(rule_ids)} item{'s' if len(rule_ids) != 1 else ''}  ({_OWNER_HINT.get(owner, '')})")
        reference = str(subject.get("reference") or "")
        lines.append(f"  Re-audit after a fix:  play audit {reference} --author")
        lines.append(f"  Share with the author: play audit {reference} --report")
    if envelope.get("history_ref"):
        lines += ["", f"stored  {envelope['history_ref']}"]
    return "\n".join(lines)


def report(envelope: dict[str, Any]) -> str:
    if envelope.get("status") != "ok":
        return f"Audit unavailable: {envelope.get('reason')}"
    subject = envelope.get("subject") or {}
    summary = envelope.get("summary") or {}
    lines = [
        f"## Audit of `{_title(envelope)}`",
        "",
        f"Package digest `{subject.get('digest')}`, audited {subject.get('audited_at')}.",
        f"{summary.get('open_facts')} fact(s), {summary.get('judgments')} judgment(s), {summary.get('unknowns')} unknown(s).",
    ]
    for title, section in (("Facts", "facts"), ("Judgments (advisory)", "judgments")):
        items = envelope.get(section) or []
        if not items:
            continue
        lines += ["", f"### {title}", ""]
        for item in items:
            lines.append(f"- **{item['id']}** `{_where(item)}` — {item['message']}")
            lines.append(f"  Fix: {item['fix']} (owner: {item['owner']})")
    unknowns = envelope.get("unknowns") or []
    if unknowns:
        lines += ["", "### Not inspected", ""]
        lines += [f"- {u['subject']}: {u['reason']}" for u in unknowns]
    return "\n".join(lines)


def history(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    rows = []
    for entry in entries:
        rows.append([
            str(entry.get("at") or ""),
            str(entry.get("event") or ""),
            f"v{entry.get('version')}",
            str(entry.get("digest") or "")[:23],
            str(entry.get("profile") or "live"),
            f"facts {entry.get('open_facts')}",
            f"judgments {entry.get('judgments')}",
            f"unknowns {entry.get('unknowns')}",
        ])
    return "\n".join(_pad(rows, indent=""))
