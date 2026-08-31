"""Render Play's harness-aware, plain-language sidekick guide."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence

from .harnesses import HARNESS_BY_ID, supported_harnesses


GUIDE_TOPICS = ("start", "run", "sources", "quiet", "create", "share", "schedule")
TOPIC_ALIASES = {
    "run": {"run", "another", "someone", "pull", "inspect", "approve", "uri"},
    "sources": {"source", "sources", "where", "community", "registry", "team", "trust"},
    "quiet": {"quiet", "match", "matches", "fallback", "silent", "none", "nothing"},
    "create": {"create", "explore", "make", "record", "save", "crystallize"},
    "share": {"share", "private", "public", "publish", "colleague", "travel"},
    "schedule": {"schedule", "recurring", "repeat", "cron", "tulving", "later"},
    "start": {"start", "hello", "first", "overview", "guide", "help"},
}


def _topic(words: Sequence[str]) -> str:
    if not words:
        return "start"
    tokens = set(re.findall(r"[a-z0-9]+", " ".join(words).lower()))
    for topic in GUIDE_TOPICS:
        if topic in tokens:
            return topic
    for topic in ("run", "sources", "quiet", "create", "share", "schedule", "start"):
        if tokens.intersection(TOPIC_ALIASES[topic]):
            return topic
    return "start"


def _surface(harness: str) -> tuple[str, str]:
    spec = HARNESS_BY_ID.get(harness)
    if spec is None:
        return "your agent", "<Play prefix>"
    return spec.label, spec.play_entry


def _header(title: str, harness: str) -> list[str]:
    label, prefix = _surface(harness)
    lines = [f"# ◆ {title}", ""]
    if harness == "generic":
        lines.extend(
            [
                "Use `$play` in Codex, `/skill:play` in Kimi, and `/play` in other supported agents.",
                "",
            ]
        )
    else:
        lines.extend([f"**{label} Play prefix:** `{prefix}`", ""])
    return lines


def _footer(prefix: str) -> list[str]:
    return [
        "",
        "---",
        "",
        "Look up one part:",
        "",
        f"`{prefix} guide run` · `{prefix} guide sources` · `{prefix} guide quiet`",
        f"`{prefix} guide create` · `{prefix} guide share` · `{prefix} guide schedule`",
    ]


def _start(harness: str, prefix: str) -> list[str]:
    lines = _header("Play sidekick guide", harness)
    lines.extend(
        [
            "> Ask for an outcome. Play offers a proven method when one fits and steps aside when none does.",
            "",
            "Rote turns a successful agent run into an inspectable, repeatable Play that can travel",
            "across harnesses, models, machines, and teams.",
            "",
            "## Start in one minute",
            "",
            f"1. See recent community Plays: `{prefix} what's new`",
            f"2. Run the safe starter: `{prefix} run hello`",
            f"3. Ask for real work: `{prefix} check recent emails`",
            "",
            "## Play takes one of two paths",
            "",
            "```text",
            "Ask → Match found → Inspect → Approve pull and run → Verified result",
            "  └→ No match     → Play steps aside → Your agent continues",
            "```",
            "",
            "A match can come from your machine, a private team, or the public community.",
            "Choosing it permits inspection only. Play shows the exact version, access, inputs,",
            "and effects before asking whether to pull and run it.",
            "",
            "## Create only when you choose to",
            "",
            f"Start with `{prefix} explore retrieve my rideshare receipts`.",
            "Play searches first. If nothing fits, you steer the work and decide whether the",
            "verified method becomes a private, team, or community Play.",
            "",
            "After a verified result, you can also ask Play to repeat it on a schedule.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


def _run(harness: str, prefix: str) -> list[str]:
    lines = _header("Run someone else's Play", harness)
    lines.extend(
        [
            "Ask for the result you want:",
            "",
            f"`{prefix} check recent emails`",
            "",
            "If Play finds a useful match, it shows the creator, exact version, required access,",
            "inputs, and effects. Choosing the result allows inspection. It does not run anything.",
            "",
            "When you select **Pull and run**, Play installs that exact version and runs the",
            "displayed method. If the Play is already local, it stays in place when byte-current.",
            "",
            "Already have a Play URI? Paste it after the prefix:",
            "",
            f"`{prefix} https://play.modiqo.ai/<owner>/<name>`",
            "",
            "If nothing matches, Play quietly returns the original request to your agent.",
            f"Use `{prefix} search <outcome>` when you want search results without that fallback.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


def _sources(harness: str, prefix: str) -> list[str]:
    lines = _header("Where Plays come from", harness)
    lines.extend(
        [
            "**Your machine**  ",
            "Plays you already installed or created.",
            "",
            "**Your teams**  ",
            "Private Plays shared through an organization you can access.",
            "",
            "**The community**  ",
            "Public Plays contributed so other people can inspect and reuse the method.",
            "",
            "This resembles sharing through GitHub, but Rote's registry distributes Plays.",
            "A remote result is never automatic permission to install or run it. Play first",
            "shows its source, version, access, inputs, and effects for your approval.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


def _quiet(harness: str, prefix: str) -> list[str]:
    lines = _header("Play gets out of the way", harness)
    lines.extend(
        [
            f"Ask for an outcome: `{prefix} check recent emails`",
            "",
            "```text",
            "Strong match   → Play offers it for inspection",
            "Possible match → Play leaves one optional suggestion",
            "No match       → Play stays quiet; your agent continues normally",
            "```",
            "",
            "Play never starts creating a new Play because search came up empty.",
            f"Creation begins only when you say `{prefix} explore <outcome>`.",
            "",
            f"An explicit `{prefix} search <outcome>` is search-only. It shows an empty result",
            "and stops instead of handing the work back to the agent.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


def _create(harness: str, prefix: str) -> list[str]:
    lines = _header("Create your own Play", harness)
    lines.extend(
        [
            "Begin with the result, not a procedure:",
            "",
            f"`{prefix} explore retrieve my rideshare receipts`",
            "",
            "```text",
            "Explore → Search existing Plays → Steer the work → Verify the result",
            "                                              └→ Save or leave it one-off",
            "```",
            "",
            "You remain the domain expert. Correct the agent, change direction, and decide when",
            "the result is right. Play observes the successful method from the start.",
            "",
            "After verification, Play asks whether to save it. Choose private, team, community,",
            "or skip. A saved Play receives a URI that can move across supported agents, machines,",
            "and teams. Later runs reuse the verified method instead of rediscovering it.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


def _share(harness: str, prefix: str) -> list[str]:
    lines = _header("Share a Play", harness)
    lines.extend(
        [
            "A verified Play can stay private, belong to a team, or be public in the community.",
            "",
            "- **Private:** keep the method for yourself.",
            "- **Team:** colleagues with organization access can inspect and run it.",
            "- **Community:** anyone can inspect the published Play and request to pull it.",
            "",
            "The registry returns a canonical Play URI. Send that URI to another person or paste",
            f"it into another supported agent after `{prefix}`.",
            "",
            "Access and execution approval still apply on every machine. Sharing a URI never",
            "silently grants credentials or permission to run effects.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


def _schedule(harness: str, prefix: str) -> list[str]:
    lines = _header("Repeat a Play later", harness)
    lines.extend(
        [
            "Scheduling starts only after a Play returns a verified successful result.",
            "Play can then offer hourly, daily, or a cadence you choose for that exact version.",
            "",
            "You approve the cadence, parameters, reason, and stop condition. Tulving keeps the",
            "future runs and their retained result envelopes. Ask what ran with:",
            "",
            "`play recurring last`",
            "",
            "To schedule an earlier verified Play, name that completed Play and the cadence.",
            "Play will not schedule a search result, an unverified run, or an unversioned reference.",
        ]
    )
    lines.extend(_footer(prefix))
    return lines


RENDERERS = {
    "start": _start,
    "run": _run,
    "sources": _sources,
    "quiet": _quiet,
    "create": _create,
    "share": _share,
    "schedule": _schedule,
}


def render_guide(*, harness: str = "generic", words: Sequence[str] = ()) -> str:
    """Return one deterministic Markdown guide selected from plain-language words."""

    topic = _topic(words)
    _, prefix = _surface(harness)
    return "\n".join(RENDERERS[topic](harness, prefix)).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explain how to find, run, create, share, and repeat Plays."
    )
    parser.add_argument(
        "--harness",
        choices=("generic", *supported_harnesses()),
        default="generic",
        help="show the Play prefix for one agent",
    )
    parser.add_argument("question", nargs="*", help="topic or plain-language question")
    args = parser.parse_args(argv)
    print(render_guide(harness=args.harness, words=args.question), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
