"""The three human renderings of one envelope.

``card``   consumer: a map of the Play, facts only, no rule ids, no counts.
``author`` author: every finding with its owner and fix, judgments included.
``report`` author to registry inbox: Markdown with the digest.
"""

from __future__ import annotations

from typing import Any

_KIND_LABEL = {"process": "runs a local command", "adapter": "calls a service", "browser": "drives a browser"}

# One plain sentence per fact class that a consumer should expect to see happen.
_EXPECTATIONS: dict[str, str] = {
    "FANOUT_OVER_PREVIEW": "Very large intermediate lists are cut at 64 KiB; the full text is kept in the run's artifacts.",
    "ADAPTER_SOURCE_PROVENANCE_DIFFERS": "The service adapter installed here comes from a different publisher than this Play expects; rote may ask you to reinstall it.",
    "ABSOLUTE_HOME_PATH": "A path inside the Play points at its author's home folder and may not exist here.",
    "BODY_STRANDED": "Part of this Play's code is never executed; the result comes only from its declared steps.",
}


def _pad(rows: list[list[str]], indent: str = "  ") -> list[str]:
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return [indent + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]


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
    lines: list[str] = [f"{subject.get('reference')}" + (f"@{subject['version']}" if subject.get("version") else "")]

    shape = envelope.get("shape") or []
    if shape:
        lines += ["", "Shape"]
        rows = []
        for index, step in enumerate(shape, 1):
            label = step.get("label") or _KIND_LABEL.get(step.get("kind"), step.get("kind") or "step")
            detail = ", ".join(step.get("commands") or []) or (step.get("endpoint") or "")
            if step.get("unread_body"):
                detail = (detail + "  " if detail else "") + "runs code this inspection could not read"
            extra = "once per item" if step.get("fan_out") else ""
            rows.append([str(index), str(step.get("name")), label, detail, extra])
        lines += _pad(rows)

    reach = envelope.get("reach") or {}
    lines += ["", "Reach"]
    rows = [
        ["Runs on this machine", ", ".join(reach.get("commands") or []) or "nothing"],
        ["Reads", ", ".join(f"{p} (you supply it)" for p in reach.get("parameters") or []) or "no parameters"],
        ["Calls", ", ".join(s.replace("adapter/", "") for s in reach.get("services") or []) or "no services"],
        ["Writes", ", ".join(reach.get("writes") or []) or "nothing declared"],
    ]
    lines += _pad(rows)

    host = envelope.get("host") or {}
    needs = host.get("needs") or []
    if needs:
        lines += ["", "Needs from this machine" if host.get("profile") == "live" else f"Needs on {host.get('label')}"]
        lines += _pad([[n["name"], _status_words(n)] for n in needs])

    # Facts only. Judgments never reach the card, by contract.
    expectations: list[str] = []
    for item in envelope.get("facts") or []:
        sentence = _EXPECTATIONS.get(str(item.get("id")))
        if sentence and sentence not in expectations:
            expectations.append(sentence)
    if expectations:
        lines += ["", "What to expect"]
        lines += [f"  {s}" for s in expectations[:3]]

    unread = reach.get("unread_bodies") or []
    skipped = [u for u in envelope.get("unknowns") or [] if u.get("kind") in {"RULES_SKIPPED", "EXTRACTOR_FAILED"}]
    if unread or skipped:
        lines += ["", "Not inspected"]
        for name in unread:
            lines.append(f"  step {name} runs code this inspection could not read")
        if skipped:
            lines.append(f"  {len(skipped)} check(s) did not run on this machine")

    summary = envelope.get("summary") or {}
    lines += ["", f"Can it run here     {'yes' if summary.get('can_run_here') else 'not yet: ' + str(summary.get('cannot_run_reason'))}"]
    return "\n".join(lines)


def author(envelope: dict[str, Any]) -> str:
    if envelope.get("status") != "ok":
        return f"audit unavailable: {envelope.get('reason')}"
    subject = envelope.get("subject") or {}
    summary = envelope.get("summary") or {}
    lines = [
        f"{subject.get('reference')}@{subject.get('version') or '?'}  digest {str(subject.get('digest'))[:23]}  {subject.get('elapsed_ms')} ms",
        f"facts {summary.get('open_facts')}  judgments {summary.get('judgments')}  unknowns {summary.get('unknowns')}  suppressed {summary.get('suppressed')}",
    ]
    for title, section in (("Facts", "facts"), ("Judgments", "judgments")):
        items = envelope.get(section) or []
        if not items:
            continue
        lines += ["", f"{title} ({len(items)})"]
        for item in items:
            loc = item.get("location") or {}
            where = loc.get("path") or (f"{loc.get('file')}:{loc.get('line')}" if loc.get("line") else loc.get("file") or "")
            precision = f"  precision {item['precision']:.0%}" if item.get("precision") is not None else ""
            lines.append(f"  {item['id']}  {where}  → {item['owner']}{precision}")
            lines.append(f"    {item['message']}")
            lines.append(f"    fix: {item['fix']}")
            if item.get("related_issue"):
                lines.append(f"    see: {item['related_issue']}")
    suppressed = envelope.get("suppressions") or []
    if suppressed:
        lines += ["", f"Suppressed ({len(suppressed)})"]
        for item in suppressed:
            lines.append(f"  {item['id']}  {item.get('suppressed_reason')}")
    unknowns = envelope.get("unknowns") or []
    if unknowns:
        lines += ["", f"Unknowns ({len(unknowns)})"]
        for item in unknowns:
            lines.append(f"  {item['kind']}  {item['subject']}: {item['reason']}")
    if envelope.get("history_ref"):
        lines += ["", f"stored: {envelope['history_ref']}"]
    return "\n".join(lines)


def report(envelope: dict[str, Any]) -> str:
    if envelope.get("status") != "ok":
        return f"Audit unavailable: {envelope.get('reason')}"
    subject = envelope.get("subject") or {}
    summary = envelope.get("summary") or {}
    lines = [
        f"## Audit of `{subject.get('reference')}@{subject.get('version') or '?'}`",
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
            loc = item.get("location") or {}
            where = loc.get("path") or (f"{loc.get('file')}:{loc.get('line')}" if loc.get("line") else loc.get("file") or "")
            lines.append(f"- **{item['id']}** `{where}` — {item['message']}")
            lines.append(f"  Fix: {item['fix']}")
    unknowns = envelope.get("unknowns") or []
    if unknowns:
        lines += ["", "### Not inspected", ""]
        lines += [f"- {u['subject']}: {u['reason']}" for u in unknowns]
    return "\n".join(lines)
