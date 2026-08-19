"""Check the complete local Play and Rote installation before Play work."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

_OK_EMAIL = re.compile(r"(?im)^ok:\s*([^@\s]+@[^@\s]+\.[^@\s]+)$")


SCHEMA = "play.preflight/v1"
ROOT = Path(__file__).resolve().parents[3]
SUPPORTED_HARNESSES = (
    "codex",
    "claude",
    "kimi",
    "cursor",
    "hermes",
    "opencode",
    "deepseek",
)
HARNESS_COMMANDS = {
    "codex": "codex",
    "claude": "claude",
    "kimi": "kimi",
    "cursor": "cursor",
    "hermes": "hermes",
    "opencode": "opencode",
    "deepseek": "dsh",
}
HARNESS_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "kimi": "Kimi",
    "cursor": "Cursor",
    "hermes": "Hermes Agent",
    "opencode": "OpenCode",
    "deepseek": "DeepSeek Harness (preview)",
}
REQUIRED_PLAY_EXECUTABLES = (
    "play-machine",
    "play-bootstrap",
    "play-birth",
    "play-activate",
    "play-certificate",
    "play-cheat-sheet",
    "play-delivery",
    "play-digest",
    "play-handoff",
    "play-inbox",
    "play-inspect",
    "play-intercept",
    "play-inventory",
    "play-journal",
    "play-journey",
    "play-onboarding",
    "play-preflight",
    "play-presentation",
    "play-public-owner",
    "play-public-trends",
    "play-publication",
    "play-publication-gate",
    "play-question",
    "play-routing",
    "play-run",
    "play-run-output",
    "play-scheduler-probe",
    "play-search",
    "play-standby",
)
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
    "kimi": [
        "Install the rote-onboard skill in ~/.agents/skills or ~/.kimi/skills.",
        "Restart Kimi, then invoke /skill:rote-setup.",
    ],
    "cursor": [
        "Install the rote-onboard skill in ~/.cursor/skills.",
        "Restart Cursor, then invoke $rote-setup.",
    ],
    "hermes": [
        "Install the rote-onboard skill in ~/.hermes/skills.",
        "Restart Hermes, then invoke /rote-setup.",
    ],
    "opencode": [
        "Install the rote-onboard skill in ~/.config/opencode/skills.",
        "Restart OpenCode and ask it to use the rote-setup skill.",
    ],
    "deepseek": [
        "Install the rote-onboard skill in ~/.agents/skills or ~/.dsh/skills.",
        "Restart DeepSeek Harness, then invoke /rote-setup.",
    ],
    "generic": [
        "Install Rote from https://github.com/modiqo/rote-skills.",
        "Run the rote-setup skill in this harness.",
    ],
}

PLAY_RESTORE_COMMANDS = {
    "codex": [
        "Run this Play skill's bundled scripts/bin/play-activate to restore the launcher and activation state.",
        "In Codex, use /skills to ensure Play is enabled.",
        "Restart Codex.",
    ],
    "claude": [
        "Run this Play skill's bundled scripts/bin/play-activate to restore the launcher and activation state.",
        "Restart Claude Code.",
    ],
    "kimi": ["Install Play in ~/.agents/skills or ~/.kimi/skills, then restart Kimi."],
    "cursor": ["Install Play in ~/.cursor/skills, then restart Cursor."],
    "hermes": ["Install Play in ~/.hermes/skills, then restart Hermes."],
    "opencode": [
        "Install Play in ~/.config/opencode/skills and its managed /play command, then restart OpenCode."
    ],
    "deepseek": [
        "Install Play in ~/.agents/skills or ~/.dsh/skills, then restart DeepSeek Harness."
    ],
    "generic": ["Reinstall the current Play skill and restart the harness."],
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


def harness_skill_roots() -> dict[str, tuple[Path, ...]]:
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
    claude_home = Path(
        os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")
    ).expanduser()
    kimi_home = Path(os.environ.get("KIMI_CONFIG_DIR", home / ".kimi")).expanduser()
    cursor_home = Path(
        os.environ.get("CURSOR_CONFIG_DIR", home / ".cursor")
    ).expanduser()
    hermes_home = Path(os.environ.get("HERMES_HOME", home / ".hermes")).expanduser()
    opencode_home = Path(
        os.environ.get("OPENCODE_CONFIG_DIR", home / ".config" / "opencode")
    ).expanduser()
    deepseek_home = Path(os.environ.get("DSH_HOME", home / ".dsh")).expanduser()
    agents_home = Path(os.environ.get("AGENTS_HOME", home / ".agents")).expanduser()
    agents_config_home = Path(
        os.environ.get("AGENTS_CONFIG_HOME", home / ".config" / "agents")
    ).expanduser()
    codex_plugin_roots = tuple(
        sorted(
            {
                *codex_home.glob("plugins/cache/*/*/*/skills"),
                *codex_home.glob(".tmp/marketplaces/*/plugins/*/skills"),
                *codex_home.glob(".tmp/bundled-marketplaces/*/plugins/*/skills"),
            },
            key=str,
        )
    )
    claude_plugin_roots = tuple(
        sorted(claude_home.glob("plugins/cache/*/*/*/skills"), key=str)
    )
    return {
        "codex": (codex_home / "skills", *codex_plugin_roots),
        "claude": (claude_home / "skills", *claude_plugin_roots),
        "kimi": (
            kimi_home / "skills",
            agents_config_home / "skills",
            agents_home / "skills",
        ),
        "cursor": (cursor_home / "skills",),
        "hermes": (hermes_home / "skills",),
        "opencode": (opencode_home / "skills", agents_home / "skills"),
        "deepseek": (deepseek_home / "skills", agents_home / "skills"),
    }


def _has_skill(root: Path, name: str) -> bool:
    if name == "play":
        return (root / "play" / "SKILL.md").is_file()
    try:
        children = root.iterdir()
    except OSError:
        return False
    return any(
        (child.name == "rote" or child.name.startswith("rote-"))
        and (child / "SKILL.md").is_file()
        for child in children
    )


def inspect_harnesses(active: str) -> list[dict[str, object]]:
    statuses = []
    for name, roots in harness_skill_roots().items():
        command = shutil.which(HARNESS_COMMANDS[name])
        installed = command is not None
        rote_roots = [str(root) for root in roots if _has_skill(root, "rote")]
        play_roots = [str(root) for root in roots if _has_skill(root, "play")]
        if not (installed or rote_roots or play_roots or name == active):
            continue
        statuses.append(
            {
                "id": name,
                "label": HARNESS_LABELS[name],
                "command": command,
                "skill_roots": [str(root) for root in roots],
                "rote_skills_installed": bool(rote_roots),
                "rote_skill_roots": rote_roots,
                "play_skill_installed": bool(play_roots),
                "play_skill_roots": play_roots,
                "selected": installed or bool(rote_roots) or bool(play_roots) or name == active,
            }
        )
    return statuses


def _runtime_bundle_check() -> Check:
    bin_root = ROOT / "scripts" / "bin"
    missing = [
        name
        for name in REQUIRED_PLAY_EXECUTABLES
        if not (bin_root / name).is_file() or not os.access(bin_root / name, os.X_OK)
    ]
    return Check(
        "play_runtime_bundle",
        not missing,
        (
            f"All {len(REQUIRED_PLAY_EXECUTABLES)} required Play entrypoints are bundled and executable."
            if not missing
            else "Missing or non-executable Play entrypoints: " + ", ".join(missing)
        ),
    )


def _python_environment_check() -> Check:
    environment_ready = importlib.util.find_spec("statemachine") is not None
    uv = shutil.which("uv")
    return Check(
        "play_python_environment",
        environment_ready or uv is not None,
        (
            "The pinned Play Python environment is already active."
            if environment_ready
            else (
                f"uv is available at {uv} to bootstrap the pinned Play Python environment."
                if uv
                else "Play needs uv or an environment containing its pinned Python dependencies."
            )
        ),
    )


def inspect(harness: str) -> dict[str, Any]:
    checks: list[Check] = []
    play_machine = shutil.which("play-machine")
    checks.append(
        Check(
            "play_machine_on_path",
            play_machine is not None,
            play_machine
            or "The play-machine launcher is not on PATH (normally ~/.local/bin/play-machine).",
        )
    )
    checks.append(_runtime_bundle_check())
    checks.append(_python_environment_check())
    harnesses = inspect_harnesses(harness)
    active_status = next((item for item in harnesses if item["id"] == harness), None)
    if harness != "generic":
        has_rote_skill = bool(active_status and active_status["rote_skills_installed"])
        checks.append(
            Check(
                "rote_skill_provider",
                has_rote_skill,
                (
                    f"Rote skills are installed for {harness}."
                    if has_rote_skill
                    else f"No rote or rote-* skill is installed for {harness}."
                ),
            )
        )
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
            # rote whoami can exit 0 while reporting "error: Not logged in", so a
            # clean exit is not proof of identity; demand the ok: email line.
            authenticated = (
                identity.returncode == 0
                and bool(_OK_EMAIL.search(identity.stdout or ""))
            )
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
    cross_harness_ready = all(
        not item["selected"]
        or (item["rote_skills_installed"] and item["play_skill_installed"])
        for item in harnesses
    )
    setup_commands: list[str] = []
    if not checks[0].ok or not checks[1].ok:
        setup_commands.extend(PLAY_RESTORE_COMMANDS[harness])
    if not checks[2].ok:
        setup_commands.append("Install uv, then rerun the Play installer to verify the pinned environment.")
    if executable is None or (active_status is not None and not active_status["rote_skills_installed"]):
        setup_commands.extend(SETUP_COMMANDS[harness])
    elif any(
        not check.ok and check.id in {"authenticated", "play_capability"}
        for check in checks
    ):
        setup_commands.append(
            "Invoke $rote-setup (or /rote-setup in Claude Code) to restore sign-in or Rote Play support."
        )
    return {
        "schema": SCHEMA,
        "ready": ready,
        "harness": harness,
        "checks": [asdict(check) for check in checks],
        "runtime": {
            "implementation": "python-entrypoint",
            "launcher": play_machine,
            "bootstrap": "active-environment" if checks[2].detail.startswith("The pinned") else "uv",
            "bundled_entrypoints": list(REQUIRED_PLAY_EXECUTABLES),
        },
        "harnesses": harnesses,
        "cross_harness_ready": cross_harness_ready,
        "install_target_prompt": {
            "selection": "multiple",
            "question": "Install the current Play skill in which harnesses?",
            "options": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "selected": item["selected"],
                    "ready": item["rote_skills_installed"],
                }
                for item in harnesses
            ],
            "command_template": "scripts/harness/install-all install --harness <id> [--harness <id> ...]",
        },
        "setup_required": not ready,
        "setup_commands": list(dict.fromkeys(setup_commands)) if not ready else [],
    }


def render(payload: dict[str, Any]) -> str:
    if payload["ready"]:
        lines = [
            "Play prerequisite ready: the Play runtime and active Rote setup are complete."
        ]
        if not payload.get("cross_harness_ready", True):
            lines.append("Other selected harnesses still need Play or Rote skill installation:")
            for harness in payload.get("harnesses", []):
                if harness.get("selected") and not (
                    harness.get("rote_skills_installed")
                    and harness.get("play_skill_installed")
                ):
                    lines.append(f"- {harness['label']}")
            lines.append(
                "Run scripts/harness/install-all targets to choose the complete target set."
            )
        return "\n".join(lines)
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
