"""Check the Rote prerequisite before Play performs registry or execution work."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Sequence


SCHEMA = "play.preflight/v1"
SETUP_COMMANDS = {
    "codex": [
        "codex plugin marketplace add modiqo/rote-skills",
        "codex plugin add rote-onboard@rote-skills",
        "Restart Codex, then invoke $rote-setup.",
    ],
    "claude": [
        "claude plugin marketplace add modiqo/rote-skills",
        "claude plugin install rote-onboard@rote-skills",
        "Restart Claude Code, then invoke /rote-setup.",
    ],
    "generic": [
        "Install Rote from https://github.com/modiqo/rote-skills.",
        "Run the rote-setup skill in this harness.",
    ],
}


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    detail: str


def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), text=True, capture_output=True, check=False, timeout=15
    )


def inspect(harness: str) -> dict[str, object]:
    checks: list[Check] = []
    executable = shutil.which("rote")
    checks.append(
        Check(
            "rote_on_path",
            executable is not None,
            executable or "The rote executable is not on PATH.",
        )
    )

    if executable is None:
        checks.extend(
            [
                Check("authenticated", False, "Rote cannot check identity until installed."),
                Check("play_capability", False, "Rote cannot check Play support until installed."),
            ]
        )
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            identity_future = executor.submit(run, [executable, "whoami"])
            capability_future = executor.submit(run, [executable, "play", "--help"])
        try:
            identity = identity_future.result()
            identity_text = (identity.stdout or identity.stderr).strip()
            authenticated = identity.returncode == 0 and bool(identity_text)
        except (OSError, subprocess.TimeoutExpired) as error:
            authenticated = False
            identity_text = f"Identity check failed: {error}"
        checks.append(
            Check(
                "authenticated",
                authenticated,
                identity_text or "Rote did not return an authenticated identity.",
            )
        )

        try:
            capability = capability_future.result()
            capability_text = (capability.stdout or capability.stderr).strip()
            has_play = capability.returncode == 0 and "rote play" in capability_text.lower()
        except (OSError, subprocess.TimeoutExpired) as error:
            has_play = False
            capability_text = f"Play capability check failed: {error}"
        checks.append(
            Check(
                "play_capability",
                has_play,
                "The installed Rote exposes `rote play`."
                if has_play
                else capability_text or "The installed Rote has no Play command.",
            )
        )

    ready = all(check.ok for check in checks)
    return {
        "schema": SCHEMA,
        "ready": ready,
        "harness": harness,
        "checks": [asdict(check) for check in checks],
        "setup_required": not ready,
        "setup_commands": [] if ready else SETUP_COMMANDS[harness],
    }


def render(payload: dict[str, Any]) -> str:
    if payload["ready"]:
        return "Play prerequisite ready: Rote is installed, authenticated, and supports Plays."
    lines = ["Play needs Rote setup before it can continue:"]
    for check in payload["checks"]:
        if not check["ok"]:
            lines.append(f"- {check['detail']}")
    lines.append("Setup:")
    lines.extend(f"  {command}" for command in payload["setup_commands"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", choices=tuple(SETUP_COMMANDS), default="generic")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = inspect(args.harness)
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else render(payload))
    return 0 if payload["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
