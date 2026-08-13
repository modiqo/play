"""Transactional cross-harness bootstrap for Play and its Rote prerequisite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


SCHEMA = "play.bootstrap/v1"
PLAN_SCHEMA = "play.bootstrap-plan/v1"
REPORT_SCHEMA = "play.bootstrap-report/v1"
SUPPORTED_HARNESSES = (
    "codex",
    "claude",
    "kimi",
    "cursor",
    "hermes",
    "opencode",
    "deepseek",
)
TARGET_IDS = {
    "codex": "codex",
    "claude": "claude-code",
    "kimi": "kimi-code-cli",
    "cursor": "cursor",
    "hermes": "hermes-agent",
    "opencode": "opencode",
    # DeepSeek Harness consumes the shared Agent Skills root. Rote does not
    # yet expose a dedicated target for this developer-preview harness.
    "deepseek": "agents-md",
}
HARNESS_COMMANDS = {
    "codex": "codex",
    "claude": "claude",
    "kimi": "kimi",
    "cursor": "cursor",
    "hermes": "hermes",
    "opencode": "opencode",
    "deepseek": "dsh",
}
LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "kimi": "Kimi",
    "cursor": "Cursor",
    "hermes": "Hermes Agent",
    "opencode": "OpenCode",
    "deepseek": "DeepSeek Harness (preview)",
}
HARNESS_LAUNCH = {
    "codex": ("codex", "$play"),
    "claude": ("claude", "/play"),
    "kimi": ("kimi", "/skill:play"),
    "cursor": ("Open Cursor", "$play"),
    "hermes": ("hermes", "/play"),
    "opencode": ("opencode", "/play"),
    "deepseek": ("dsh web", "/play"),
}
ROTE_SKILL_PROVIDERS = {
    "codex": ("Codex", "CODEX_HOME", ".codex"),
    "claude-code": ("Claude Code", "CLAUDE_CONFIG_DIR", ".claude"),
    "agents-md": ("Shared .agents", "AGENTS_HOME", ".agents"),
    "cursor": ("Cursor", "CURSOR_CONFIG_DIR", ".cursor"),
    "kimi-code-cli": ("Kimi Code", "KIMI_CONFIG_DIR", ".kimi"),
    "hermes-agent": ("Hermes Agent", "HERMES_HOME", ".hermes"),
    "opencode": ("OpenCode", "OPENCODE_CONFIG_DIR", ".config/opencode"),
    "deepseek": ("DeepSeek Harness", "DSH_HOME", ".dsh"),
}
PLAY_MARKETPLACE = "play-skills"
PLAY_PLUGIN = "play@play-skills"
PLAY_REPOSITORY = "modiqo/play"


class BootstrapError(RuntimeError):
    """The bootstrap could not safely continue."""


@dataclass(frozen=True)
class HarnessTarget:
    id: str
    label: str
    command: str | None
    skill_roots: tuple[str, ...]
    rote_skills_installed: bool
    play_skill_installed: bool
    hooks: str
    score: int
    selected: bool
    selection_reason: str


@dataclass(frozen=True)
class Step:
    id: str
    status: str
    detail: str
    command: list[str] | None = None
    target: str | None = None
    changed: bool = False
    evidence: str | None = None


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _home() -> Path:
    return Path.home()


def _roots() -> dict[str, tuple[Path, ...]]:
    home = _home()
    codex = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    kimi = Path(os.environ.get("KIMI_CONFIG_DIR", home / ".kimi")).expanduser()
    cursor = Path(os.environ.get("CURSOR_CONFIG_DIR", home / ".cursor")).expanduser()
    hermes = Path(os.environ.get("HERMES_HOME", home / ".hermes")).expanduser()
    opencode = Path(
        os.environ.get("OPENCODE_CONFIG_DIR", home / ".config" / "opencode")
    ).expanduser()
    deepseek = Path(os.environ.get("DSH_HOME", home / ".dsh")).expanduser()
    agents = Path(os.environ.get("AGENTS_HOME", home / ".agents")).expanduser()
    agents_config = Path(
        os.environ.get("AGENTS_CONFIG_HOME", home / ".config" / "agents")
    ).expanduser()
    return {
        "codex": (codex / "skills",),
        "claude": (claude / "skills",),
        "kimi": (kimi / "skills", agents_config / "skills", agents / "skills"),
        "cursor": (cursor / "skills",),
        "hermes": (hermes / "skills",),
        "opencode": (opencode / "skills", agents / "skills"),
        "deepseek": (deepseek / "skills", agents / "skills"),
    }


def _has_skill(root: Path, kind: str) -> bool:
    if kind == "play":
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


def resolve_rote() -> str | None:
    if executable := shutil.which("rote"):
        return executable
    for candidate in (_home() / ".local" / "bin" / "rote", _home() / ".cargo" / "bin" / "rote"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), text=True, capture_output=True, check=False, timeout=900
    )


def _probe_version(rote: str | None, runner: Runner) -> str | None:
    if rote is None:
        return None
    result = runner([rote, "version"])
    text = (result.stdout or result.stderr).strip()
    for line in text.splitlines():
        if line.startswith("version:"):
            return line.partition(":")[2].strip()
    return text or None


def _probe_identity(rote: str | None, runner: Runner) -> str:
    if rote is None:
        return "unavailable"
    result = runner([rote, "whoami"])
    output = (result.stdout or result.stderr).strip()
    return "authenticated" if result.returncode == 0 and "ok:" in output else "required"


def _probe_update(rote: str | None, runner: Runner) -> dict[str, str | None]:
    if rote is None:
        return {
            "status": "not_installed",
            "detail": "Rote is not installed.",
            "recommended_action": "install",
        }
    result = runner([rote, "self-update", "--check"])
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return {
            "status": "check_failed",
            "detail": output or f"update check exited {result.returncode}",
            "recommended_action": "review",
        }
    normalized = output.lower()
    current_markers = (
        "latest version",
        "already current",
        "up to date",
        "up-to-date",
        "no update available",
        "rote is current",
    )
    current = any(marker in normalized for marker in current_markers)
    return {
        "status": "current" if current else "available",
        "detail": output or "Rote reports that an update is available.",
        "recommended_action": "keep" if current else "update",
    }


def _rote_snapshot(runner: Runner, *, check_update: bool = True) -> dict[str, Any]:
    rote = resolve_rote()
    snapshot = {
        "path": rote,
        "version": _probe_version(rote, runner),
        "identity": _probe_identity(rote, runner),
    }
    if check_update:
        snapshot["update"] = _probe_update(rote, runner)
    return snapshot


def _rote_skill_roots() -> dict[str, tuple[str, Path]]:
    roots: dict[str, tuple[str, Path]] = {}
    for provider, (label, variable, default) in ROTE_SKILL_PROVIDERS.items():
        home = Path(os.environ.get(variable, _home() / default)).expanduser()
        roots[provider] = (label, home / "skills")
    return roots


def _rote_skills_snapshot(providers: Sequence[str] | None = None) -> list[dict[str, Any]]:
    result = []
    roots = _rote_skill_roots()
    names = list(dict.fromkeys(providers or roots.keys()))
    for provider in names:
        label, root = roots[provider]
        try:
            names = sorted(
                child.name
                for child in root.iterdir()
                if (child.name == "rote" or child.name.startswith("rote-"))
                and (child / "SKILL.md").is_file()
            )
        except OSError:
            names = []
        installed = bool(names)
        result.append(
            {
                "provider": provider,
                "label": label,
                "root": str(root),
                "installed": installed,
                "skill_count": len(names),
                "skills": names,
                "recommended_action": "refresh" if installed else "install",
            }
        )
    return result


def _rote_skill_command(rote: str, selected: Sequence[str]) -> list[str]:
    command = [rote, "install", "skill"]
    for target in dict.fromkeys(TARGET_IDS[name] for name in selected):
        command.extend(["--target", target])
    command.extend(["--personal", "--package", "*", "--force"])
    return command


def discover_targets(*, top_k: int, requested: Sequence[str] | None = None) -> list[HarnessTarget]:
    if top_k < 1:
        raise BootstrapError("top-k must be at least 1")
    unknown = sorted(set(requested or ()) - set(SUPPORTED_HARNESSES))
    if unknown:
        raise BootstrapError("unsupported harness name(s): " + ", ".join(unknown))

    candidates: list[dict[str, Any]] = []
    for order, name in enumerate(SUPPORTED_HARNESSES):
        roots = _roots()[name]
        command = shutil.which(HARNESS_COMMANDS[name])
        rote_ready = any(_has_skill(root, "rote") for root in roots)
        play_ready = any(_has_skill(root, "play") for root in roots)
        present = command is not None or rote_ready or play_ready
        score = (100 if command else 0) + (30 if rote_ready else 0) + (20 if play_ready else 0) + (10 - order)
        candidates.append(
            {
                "id": name,
                "label": LABELS[name],
                "command": command,
                "skill_roots": tuple(str(root) for root in roots),
                "rote_skills_installed": rote_ready,
                "play_skill_installed": play_ready,
                "hooks": "managed" if name in {"codex", "claude", "cursor"} else "not_required",
                "score": score,
                "present": present,
            }
        )
    if requested:
        selected = set(requested)
    else:
        ranked = sorted(
            (item for item in candidates if item["present"]),
            key=lambda item: (-int(item["score"]), SUPPORTED_HARNESSES.index(str(item["id"]))),
        )
        selected = {str(item["id"]) for item in ranked[:top_k]}
    return [
        HarnessTarget(
            **{key: value for key, value in item.items() if key != "present"},
            selected=item["id"] in selected,
            selection_reason=(
                "explicitly selected"
                if requested and item["id"] in selected
                else (
                    f"selected in top {top_k}"
                    if item["id"] in selected
                    else ("not detected" if not item["present"] else f"outside top {top_k}")
                )
            ),
        )
        for item in candidates
    ]


def build_plan(
    *, top_k: int = 3, requested: Sequence[str] | None = None, runner: Runner = run
) -> dict[str, Any]:
    targets = discover_targets(top_k=top_k, requested=requested)
    selected = [target.id for target in targets if target.selected]
    if not selected:
        raise BootstrapError("no supported harnesses were detected or selected")
    rote_state = _rote_snapshot(runner)
    rote = rote_state["path"]
    update = rote_state["update"]
    if rote is None:
        rote_action = {
            "id": "install_rote",
            "effect": "downloads and installs executable code",
            "approval_required": True,
            "recommended": True,
        }
    elif update["status"] == "available":
        rote_action = {
            "id": "update_rote",
            "effect": update["detail"],
            "command": ["rote", "self-update", "--yes"],
            "recommended": True,
        }
    elif update["status"] == "current":
        rote_action = {
            "id": "keep_rote_current",
            "effect": update["detail"],
            "recommended": False,
        }
    else:
        rote_action = {
            "id": "review_rote_update",
            "effect": f"Update availability could not be determined: {update['detail']}",
            "recommended": False,
        }
    rote_targets = list(dict.fromkeys(TARGET_IDS[name] for name in selected))
    rote_skills = _rote_skills_snapshot(rote_targets)
    missing_skill_roots = [item["provider"] for item in rote_skills if not item["installed"]]
    existing_skill_roots = [item["provider"] for item in rote_skills if item["installed"]]
    actions = [
        rote_action,
        {
            "id": "converge_rote_skills",
            "effect": "installs missing and refreshes existing bundled Rote skills in personal harness roots",
            "missing_providers": missing_skill_roots,
            "refresh_providers": existing_skill_roots,
            "command": _rote_skill_command("rote", selected),
            "recommended": True,
        },
        {
            "id": "converge_play_marketplaces",
            "effect": "refreshes the Play marketplace, removes stale plugin caches, and reinstalls Play before Codex or Claude starts",
            "targets": [name for name in selected if name in {"codex", "claude"}],
            "commands": {
                "codex": [
                    ["codex", "plugin", "marketplace", "upgrade", PLAY_MARKETPLACE],
                    ["codex", "plugin", "remove", PLAY_PLUGIN],
                    ["codex", "plugin", "add", PLAY_PLUGIN],
                ],
                "claude": [
                    ["claude", "plugin", "marketplace", "update", PLAY_MARKETPLACE],
                    ["claude", "plugin", "uninstall", PLAY_PLUGIN, "--scope", "user", "--yes"],
                    ["claude", "plugin", "install", PLAY_PLUGIN, "--scope", "user", "--yes"],
                ],
            },
            "recommended": True,
        },
        {
            "id": "install_play",
            "effect": "copies Play and activates it in selected harness roots",
            "targets": selected,
        },
        {
            "id": "install_hooks",
            "effect": "merges managed Play pre, post, and session hooks while preserving unrelated hooks",
            "targets": [target.id for target in targets if target.selected and target.hooks == "managed"],
        },
        {"id": "verify_and_report", "effect": "runs preflight checks and writes JSON and Markdown receipts"},
    ]
    body = {
        "schema": PLAN_SCHEMA,
        "top_k": top_k,
        "selected_harnesses": selected,
        "targets": [asdict(target) for target in targets],
        "rote": rote_state,
        "rote_skills": rote_skills,
        "actions": actions,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {**body, "plan_id": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _hook_paths() -> dict[str, Path]:
    home = _home()
    return {
        "codex": Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser() / "hooks.json",
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser() / "settings.json",
        "cursor": Path(os.environ.get("CURSOR_CONFIG_DIR", home / ".cursor")).expanduser() / "hooks.json",
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"cannot safely read hook configuration {path}: {error}") from error
    if not isinstance(value, dict):
        raise BootstrapError(f"hook configuration must contain an object: {path}")
    return value


def _command_json(
    result: subprocess.CompletedProcess[str], command: Sequence[str]
) -> Any:
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise BootstrapError(
            f"command failed ({shlex.join(command)}): {output or f'exit {result.returncode}'}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BootstrapError(
            f"command returned invalid JSON ({shlex.join(command)}): {error}"
        ) from error


def _marketplace_names(harness: str, value: Any) -> set[str]:
    if harness == "codex":
        if not isinstance(value, dict) or not isinstance(value.get("marketplaces"), list):
            raise BootstrapError("Codex marketplace list returned an unexpected shape")
        records = value["marketplaces"]
    elif harness == "claude":
        if not isinstance(value, list):
            raise BootstrapError("Claude marketplace list returned an unexpected shape")
        records = value
    else:
        raise BootstrapError(f"Play marketplace convergence is unsupported for {harness}")
    return {
        str(record.get("name"))
        for record in records
        if isinstance(record, dict) and isinstance(record.get("name"), str)
    }


def _play_plugin_record(
    harness: str, value: Any, *, scope: str | None = None
) -> dict[str, Any] | None:
    if harness == "codex":
        if not isinstance(value, dict) or not isinstance(value.get("installed"), list):
            raise BootstrapError("Codex plugin list returned an unexpected shape")
        records = value["installed"]
        key = "pluginId"
    elif harness == "claude":
        if not isinstance(value, list):
            raise BootstrapError("Claude plugin list returned an unexpected shape")
        records = value
        key = "id"
    else:
        raise BootstrapError(f"Play marketplace convergence is unsupported for {harness}")
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get(key) == PLAY_PLUGIN
    ]
    if harness == "claude" and scope is not None:
        return next((record for record in matches if record.get("scope") == scope), None)
    return matches[0] if matches else None


def _marketplace_list_command(harness: str, executable: str) -> list[str]:
    return [executable, "plugin", "marketplace", "list", "--json"]


def _plugin_list_command(harness: str, executable: str) -> list[str]:
    if harness == "codex":
        return [
            executable,
            "plugin",
            "list",
            "--marketplace",
            PLAY_MARKETPLACE,
            "--json",
            "--available",
        ]
    return [executable, "plugin", "list", "--json"]


def converge_play_marketplace(
    harness: str,
    executable: str,
    *,
    expected_version: str,
    runner: Runner,
) -> list[Step]:
    """Refresh and reinstall the harness-native Play plugin before startup."""

    steps: list[Step] = []
    marketplace_list = _marketplace_list_command(harness, executable)
    marketplace_result = runner(marketplace_list)
    try:
        marketplaces = _marketplace_names(
            harness, _command_json(marketplace_result, marketplace_list)
        )
    except BootstrapError as error:
        return [
            Step(
                "inspect_play_marketplace",
                "failed",
                str(error),
                command=marketplace_list,
                target=harness,
            )
        ]
    steps.append(
        Step(
            "inspect_play_marketplace",
            "completed",
            f"Inspected configured {harness} marketplaces.",
            command=marketplace_list,
            target=harness,
        )
    )

    if PLAY_MARKETPLACE in marketplaces:
        refresh_command = [
            executable,
            "plugin",
            "marketplace",
            "upgrade" if harness == "codex" else "update",
            PLAY_MARKETPLACE,
        ]
        refresh_id = "refresh_play_marketplace"
    else:
        refresh_command = [
            executable,
            "plugin",
            "marketplace",
            "add",
            PLAY_REPOSITORY,
        ]
        refresh_id = "add_play_marketplace"
    refresh_result = runner(refresh_command)
    steps.append(
        _result_step(refresh_id, refresh_result, refresh_command, target=harness)
    )
    if refresh_result.returncode != 0:
        return steps

    plugin_list = _plugin_list_command(harness, executable)
    plugin_result = runner(plugin_list)
    scope = "user"
    try:
        existing = _play_plugin_record(
            harness,
            _command_json(plugin_result, plugin_list),
            scope=scope if harness == "claude" else None,
        )
    except BootstrapError as error:
        steps.append(
            Step(
                "inspect_play_plugin",
                "failed",
                str(error),
                command=plugin_list,
                target=harness,
            )
        )
        return steps
    steps.append(
        Step(
            "inspect_play_plugin",
            "completed",
            (
                f"Found Play {existing.get('version', 'unknown')} before reinstall."
                if existing
                else "Play was not installed before convergence."
            ),
            command=plugin_list,
            target=harness,
        )
    )

    if existing is not None:
        if harness == "codex":
            remove_command = [executable, "plugin", "remove", PLAY_PLUGIN]
        else:
            remove_command = [
                executable,
                "plugin",
                "uninstall",
                PLAY_PLUGIN,
                "--scope",
                scope,
                "--yes",
            ]
        remove_result = runner(remove_command)
        steps.append(
            _result_step(
                "remove_stale_play_plugin",
                remove_result,
                remove_command,
                target=harness,
            )
        )
        if remove_result.returncode != 0:
            return steps
    else:
        steps.append(
            Step(
                "remove_stale_play_plugin",
                "unchanged",
                "No installed Play plugin needed removal.",
                target=harness,
            )
        )

    if harness == "codex":
        install_command = [executable, "plugin", "add", PLAY_PLUGIN]
    else:
        install_command = [
            executable,
            "plugin",
            "install",
            PLAY_PLUGIN,
            "--scope",
            scope,
            "--yes",
        ]
    install_result = runner(install_command)
    steps.append(
        _result_step(
            "install_current_play_plugin",
            install_result,
            install_command,
            target=harness,
        )
    )
    if install_result.returncode != 0:
        return steps

    verify_result = runner(plugin_list)
    try:
        installed = _play_plugin_record(
            harness,
            _command_json(verify_result, plugin_list),
            scope=scope if harness == "claude" else None,
        )
    except BootstrapError as error:
        steps.append(
            Step(
                "verify_play_plugin",
                "failed",
                str(error),
                command=plugin_list,
                target=harness,
            )
        )
        return steps
    installed_version = installed.get("version") if installed else None
    enabled = installed.get("enabled") if installed else None
    plugin_errors = installed.get("errors") if installed else None
    healthy = not plugin_errors
    verified = installed_version == expected_version and enabled is not False and healthy
    steps.append(
        Step(
            "verify_play_plugin",
            "completed" if verified else "failed",
            (
                f"Play {installed_version} is installed, enabled, and healthy."
                if verified
                else (
                    f"Expected Play {expected_version} enabled after reinstall; "
                    f"found version={installed_version!r}, enabled={enabled!r}, "
                    f"errors={plugin_errors!r}."
                )
            ),
            command=plugin_list,
            target=harness,
            evidence=json.dumps(installed, sort_keys=True) if installed else None,
        )
    )
    return steps


def _is_play_skill_config(entry: dict[str, Any]) -> bool:
    if entry.get("name") == "play":
        return True
    path = entry.get("path")
    if not isinstance(path, str):
        return False
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.endswith("/skills/play/SKILL.md") or normalized.endswith(
        "/skills/play"
    )


def _fallback_skill_config_entries(text: str) -> list[dict[str, Any]]:
    """Read the small [[skills.config]] surface on Python 3.10 without tomllib."""

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "[[skills.config]]":
            current = {}
            entries.append(current)
            continue
        if line.startswith("["):
            current = None
            continue
        if current is None or not line or line.startswith("#"):
            continue
        match = re.match(r"^(name|path|enabled)\s*=\s*(.+?)\s*$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        if key == "enabled":
            if raw_value in {"true", "false"}:
                current[key] = raw_value == "true"
            continue
        if (
            len(raw_value) >= 2
            and raw_value[0] == raw_value[-1]
            and raw_value[0] in {'"', "'"}
        ):
            current[key] = raw_value[1:-1]
    return entries


def _codex_skill_config_entries(text: str, path: Path) -> list[dict[str, Any]]:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 bootstrap path.
        return _fallback_skill_config_entries(text)
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise BootstrapError(f"cannot safely read Codex configuration {path}: {error}") from error
    skills = value.get("skills")
    if not isinstance(skills, dict):
        return []
    entries = skills.get("config", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise BootstrapError(f"Codex skills.config must be a list in {path}")
    return [entry for entry in entries if isinstance(entry, dict)]


def codex_disabled_play_entries() -> list[str]:
    codex_home = Path(os.environ.get("CODEX_HOME", _home() / ".codex")).expanduser()
    path = codex_home / "config.toml"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise BootstrapError(f"cannot safely read Codex configuration {path}: {error}") from error
    entries = _codex_skill_config_entries(text, path)
    return [
        str(entry.get("path") or entry.get("name") or "play")
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("enabled") is False
        and _is_play_skill_config(entry)
    ]


def codex_play_enablement_step() -> Step:
    disabled_entries = codex_disabled_play_entries()
    if disabled_entries:
        return Step(
            "enable_play_skill",
            "human_action_required",
            "Codex has an explicit disabled Play skill override. Open /skills, enable Play, then restart Codex.",
            target="codex",
            evidence=json.dumps(disabled_entries),
        )
    return Step(
        "enable_play_skill",
        "completed",
        "No explicit disabled Play skill override was found in Codex.",
        target="codex",
    )


def _is_play_hook(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    if isinstance(command, str) and ("play-intercept" in command or "play-inbox" in command):
        return True
    hooks = value.get("hooks")
    return isinstance(hooks, list) and any(_is_play_hook(item) for item in hooks)


def _nested_hook(command: str, *, matcher: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hooks": [{"type": "command", "command": command, "timeout": 5}]
    }
    if matcher:
        value["matcher"] = matcher
    return value


def _managed_hook_entries(harness: str, source: Path) -> dict[str, list[dict[str, Any]]]:
    intercept = shlex.quote(str(source / "scripts" / "bin" / "play-intercept"))
    inbox = shlex.quote(str(source / "scripts" / "bin" / "play-inbox"))
    prompt = f"{intercept} prompt 2>/dev/null || true"
    stop = f"{intercept} settle-nudge 2>/dev/null || true"
    session = f"{inbox} line 2>/dev/null; ({inbox} refresh --if-older-than 6 >/dev/null 2>&1 &)"
    if harness in {"codex", "claude"}:
        return {
            "UserPromptSubmit": [_nested_hook(prompt)],
            "Stop": [_nested_hook(stop)],
            "SessionStart": [_nested_hook(session, matcher="startup|resume")],
        }
    if harness == "cursor":
        return {
            "beforeSubmitPrompt": [{"command": prompt, "timeout": 5}],
            "stop": [{"command": stop, "timeout": 5}],
            "sessionStart": [{"command": session, "timeout": 5}],
        }
    raise BootstrapError(f"hooks are unsupported for {harness}")


def install_hooks(harness: str, source: Path, *, run_id: str) -> Step:
    path = _hook_paths().get(harness)
    if path is None:
        return Step("install_hooks", "unsupported", "No verified native hook surface.", target=harness)
    value = _load_json(path)
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BootstrapError(f"hooks must be an object in {path}")
    desired = _managed_hook_entries(harness, source)
    changed = False
    for event, entries in desired.items():
        current = hooks.get(event, [])
        if not isinstance(current, list):
            raise BootstrapError(f"hook event {event} must be a list in {path}")
        preserved = [entry for entry in current if not _is_play_hook(entry)]
        updated = [*preserved, *entries]
        if updated != current:
            hooks[event] = updated
            changed = True
    if harness == "cursor" and value.get("version") != 1:
        value["version"] = 1
        changed = True
    if not changed:
        return Step("install_hooks", "unchanged", f"Managed hooks already active in {path}.", target=harness)
    backup: Path | None = None
    if path.exists():
        backup = path.with_name(f"{path.name}.play-backup-{run_id}")
        if backup.exists():
            raise BootstrapError(f"refusing to replace existing hook backup: {backup}")
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    _atomic_json(path, value)
    return Step(
        "install_hooks",
        "completed",
        f"Installed managed pre, post, and session hooks in {path}.",
        target=harness,
        changed=True,
        evidence=str(backup) if backup else str(path),
    )


def _result_step(
    step_id: str,
    result: subprocess.CompletedProcess[str],
    command: Sequence[str],
    *,
    target: str | None = None,
) -> Step:
    output = (result.stdout or result.stderr).strip()
    return Step(
        step_id,
        "completed" if result.returncode == 0 else "failed",
        output or f"exit {result.returncode}",
        command=list(command),
        target=target,
        changed=result.returncode == 0,
    )


def _report_root() -> Path:
    override = os.environ.get("PLAY_BOOTSTRAP_STATE")
    if override:
        return Path(override).expanduser().resolve()
    state = Path(os.environ.get("XDG_STATE_HOME", _home() / ".local" / "state")).expanduser()
    return state / "play-bootstrap"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Play bootstrap report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Status: **{report['status']}**",
        f"- Plan: `{report['plan_id']}`",
        f"- Started: {report['started_at']}",
        f"- Finished: {report['finished_at']}",
        "",
        "## Selected harnesses",
        "",
    ]
    lines.extend(f"- {name}" for name in report["selected_harnesses"])
    lines.extend(["", "## Steps", ""])
    for step in report["steps"]:
        target = f" ({step['target']})" if step.get("target") else ""
        lines.append(f"- **{step['status']}** `{step['id']}`{target}: {step['detail']}")
    lines.extend(["", "## Restart", "", report["restart"]])
    report_paths = report.get("report_paths")
    if isinstance(report_paths, dict):
        lines.extend(
            [
                "",
                "## Saved reports",
                "",
                f"- JSON: `{report_paths.get('json')}`",
                f"- Markdown: `{report_paths.get('markdown')}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _render_status_card(report: dict[str, Any]) -> str:
    """Render the curl installer's concise, action-oriented final screen."""

    status = str(report["status"])
    status_label = {
        "completed": "READY",
        "action_required": "READY — ACTION REQUIRED",
        "blocked": "INCOMPLETE",
    }.get(status, status.upper())
    steps = [step for step in report["steps"] if isinstance(step, dict)]
    general_blocker = any(
        step.get("status") in {"failed", "approval_required"}
        and step.get("target") is None
        for step in steps
    )
    lines = [
        "",
        "+------------------------------------------------------------+",
        "| Play setup                                                 |",
        "+------------------------------------------------------------+",
        f"  Status: {status_label}",
        f"  Run:    {report['run_id']}",
        "",
        "  Apps",
    ]
    for harness in report["selected_harnesses"]:
        harness_steps = [step for step in steps if step.get("target") == harness]
        if general_blocker or any(
            step.get("status") in {"failed", "approval_required"}
            for step in harness_steps
        ):
            state = "INCOMPLETE"
        elif any(
            step.get("status") in {"human_action_required", "review_required"}
            for step in harness_steps
        ):
            state = "ACTION REQUIRED"
        else:
            state = "READY"
        lines.append(f"    {LABELS.get(harness, harness):<14} {state}")

    action_steps = [
        step
        for step in steps
        if step.get("status")
        in {"failed", "approval_required", "human_action_required", "review_required"}
    ]
    if action_steps:
        lines.extend(["", "  Before you start"])
        for step in action_steps:
            target = step.get("target")
            prefix = f"{LABELS.get(str(target), str(target))}: " if target else ""
            lines.append(f"    - {prefix}{step.get('detail', 'Review the saved report.')}")

    if status != "blocked":
        lines.extend(["", "  Next steps"])
        number = 1
        for harness in report["selected_harnesses"]:
            launch = HARNESS_LAUNCH.get(str(harness))
            if launch is None:
                continue
            command, invocation = launch
            lines.append(f"    {number}. Start {LABELS.get(str(harness), harness)}: {command}")
            lines.append(f"       In a new conversation, type: {invocation}")
            number += 1

        invocations = list(
            dict.fromkeys(
                HARNESS_LAUNCH[str(harness)][1]
                for harness in report["selected_harnesses"]
                if str(harness) in HARNESS_LAUNCH
            )
        )
        if invocations:
            lines.extend(["", "  Try these"])
            for invocation in invocations:
                matching = [
                    LABELS.get(str(harness), str(harness))
                    for harness in report["selected_harnesses"]
                    if HARNESS_LAUNCH.get(str(harness), (None, None))[1] == invocation
                ]
                label = " / ".join(matching)
                lines.append(f"    {label}:")
                lines.append(f"      {invocation} whats new")
                lines.append(f"      {invocation} find a Play for my task")
                lines.append(f"      {invocation} run <Play name>")

    report_paths = report.get("report_paths")
    if isinstance(report_paths, dict):
        lines.extend(
            [
                "",
                "  Detailed report",
                f"    {report_paths.get('markdown')}",
                f"    {report_paths.get('json')}",
            ]
        )
    lines.extend(["+------------------------------------------------------------+", ""])
    return "\n".join(lines)


def _render_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# Play bootstrap plan",
        "",
        f"Plan: `{plan['plan_id']}`",
        "",
        "## Rote",
        "",
    ]
    rote = plan["rote"]
    if rote["path"]:
        lines.append(f"- Installed: `{rote['version'] or 'unknown version'}` at `{rote['path']}`")
    else:
        lines.append("- Not installed")
    update = rote["update"]
    lines.append(
        f"- Update check: **{update['status']}** — {update['detail']}"
    )
    lines.extend(["", "## Rote skills", ""])
    for item in plan["rote_skills"]:
        state = f"{item['skill_count']} installed" if item["installed"] else "not installed"
        lines.append(
            f"- {item['label']}: **{state}** at `{item['root']}`; "
            f"suggested action: **{item['recommended_action']}**"
        )
    lines.extend(
        [
            "",
        "## Selected harnesses",
        "",
        ]
    )
    lines.extend(f"- {name}" for name in plan["selected_harnesses"])
    lines.extend(["", "## Actions", ""])
    for action in plan["actions"]:
        approval = "; explicit approval required" if action.get("approval_required") else ""
        lines.append(f"- `{action['id']}`: {action['effect']}{approval}")
    return "\n".join(lines) + "\n"


def _confirm(question: str, *, default: bool) -> bool:
    """Read an approval from the controlling terminal, even when the installer is piped."""

    prompt = " [Y/n] " if default else " [y/N] "
    stream = None
    close_stream = False
    if sys.stdin.isatty() and sys.stderr.isatty():
        stream = sys.stdin
    else:
        try:
            stream = open("/dev/tty", "r+", encoding="utf-8")
            close_stream = True
        except OSError as error:
            raise BootstrapError(
                "interactive approval is unavailable; rerun with --yes to approve the Play "
                "plan and, if Rote is missing, --approve-remote-installer to separately "
                "approve https://getrote.dev/install"
            ) from error
    try:
        if stream is sys.stdin:
            print(question + prompt, end="", file=sys.stderr, flush=True)
        else:
            stream.write(question + prompt)
            stream.flush()
        answer = stream.readline()
    finally:
        if close_stream:
            stream.close()
    if not answer:
        raise BootstrapError("interactive approval ended before a choice was received")
    normalized = answer.strip().lower()
    if not normalized:
        return default
    if normalized in {"y", "yes"}:
        return True
    if normalized in {"n", "no"}:
        return False
    raise BootstrapError("approval must be yes or no")


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    root = _report_root() / "runs"
    json_path = root / f"{report['run_id']}.json"
    markdown_path = root / f"{report['run_id']}.md"
    if json_path.exists() or markdown_path.exists():
        raise BootstrapError(f"report already exists for run {report['run_id']}")
    _atomic_json(json_path, report)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    markdown_path.chmod(0o600)
    return json_path, markdown_path


def apply(
    source: Path,
    *,
    top_k: int = 3,
    requested: Sequence[str] | None = None,
    approve_remote_installer: bool = False,
    runner: Runner = run,
    run_id: str | None = None,
    expected_plan_id: str | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = datetime.now(timezone.utc).isoformat()
    plan = build_plan(top_k=top_k, requested=requested, runner=runner)
    if expected_plan_id is not None and expected_plan_id != plan["plan_id"]:
        raise BootstrapError(
            f"plan changed: expected {expected_plan_id}, got {plan['plan_id']}"
        )
    selected = list(plan["selected_harnesses"])
    steps: list[Step] = []
    rote = resolve_rote()
    initially_present = rote is not None

    if rote is None:
        if not approve_remote_installer:
            steps.append(
                Step(
                    "install_rote",
                    "approval_required",
                    "Approve the official remote installer, then resume with --approve-remote-installer.",
                    command=["bash", "-c", "$(curl -fsSL https://getrote.dev/install)"],
                )
            )
        else:
            command = [
                "bash",
                "-c",
                'ROTE_YES=1 ROTE_FULL=1 bash -c "$(curl --proto \'=https\' --tlsv1.2 -fsSL https://getrote.dev/install)"',
            ]
            result = runner(command)
            steps.append(_result_step("install_rote", result, command))
            rote = resolve_rote()
            if result.returncode != 0 or rote is None:
                return _finish_report(plan, run_id, started, steps, status="blocked", runner=runner)
    update_status = plan["rote"]["update"]["status"]
    if initially_present and rote is not None and update_status == "available":
        command = [rote, "self-update", "--yes"]
        result = runner(command)
        steps.append(_result_step("update_rote", result, command))
        if result.returncode != 0:
            return _finish_report(plan, run_id, started, steps, status="blocked", runner=runner)
    elif initially_present and rote is not None:
        detail = plan["rote"]["update"]["detail"]
        steps.append(
            Step(
                "check_rote_update",
                "unchanged" if update_status == "current" else "review_required",
                detail,
                command=[rote, "self-update", "--check"],
            )
        )

    if rote is None:
        return _finish_report(plan, run_id, started, steps, status="blocked", runner=runner)

    skill_command = _rote_skill_command(rote, selected)
    skill_result = runner(skill_command)
    missing = [item["label"] for item in plan["rote_skills"] if not item["installed"]]
    refreshed = [item["label"] for item in plan["rote_skills"] if item["installed"]]
    coverage = []
    if missing:
        coverage.append("installed " + ", ".join(missing))
    if refreshed:
        coverage.append("refreshed " + ", ".join(refreshed))
    skill_output = (skill_result.stdout or skill_result.stderr).strip()
    detail = "; ".join(coverage)
    if skill_output:
        detail = f"{detail}. {skill_output}" if detail else skill_output
    steps.append(
        Step(
            "converge_rote_skills",
            "completed" if skill_result.returncode == 0 else "failed",
            detail or f"exit {skill_result.returncode}",
            command=skill_command,
            changed=skill_result.returncode == 0,
        )
    )
    if skill_result.returncode != 0:
        return _finish_report(plan, run_id, started, steps, status="blocked", runner=runner)

    expected_version = (source / "VERSION").read_text(encoding="utf-8").strip()
    plan_targets = {
        str(target["id"]): target
        for target in plan["targets"]
        if isinstance(target, dict) and isinstance(target.get("id"), str)
    }
    for harness in selected:
        target = plan_targets.get(harness, {})
        executable = target.get("command") if isinstance(target, dict) else None
        if not isinstance(executable, str) or not executable:
            steps.append(
                Step(
                    "locate_harness",
                    "human_action_required",
                    f"{LABELS[harness]} is not on PATH as `{HARNESS_COMMANDS[harness]}`. Play files will be prepared, but install or expose the app command before launching it.",
                    target=harness,
                )
            )
    for harness in selected:
        if harness not in {"codex", "claude"}:
            continue
        target = plan_targets.get(harness, {})
        executable = target.get("command") if isinstance(target, dict) else None
        if not isinstance(executable, str) or not executable:
            continue
        marketplace_steps = converge_play_marketplace(
            harness,
            executable,
            expected_version=expected_version,
            runner=runner,
        )
        steps.extend(marketplace_steps)
        if any(step.status == "failed" for step in marketplace_steps):
            return _finish_report(
                plan, run_id, started, steps, status="blocked", runner=runner
            )

    if "codex" in selected:
        steps.append(codex_play_enablement_step())

    installer = source / "scripts" / "harness" / "install-all"
    install_command = [str(installer), "install", "--copy"]
    for harness in selected:
        install_command.extend(["--harness", harness])
    install_result = runner(install_command)
    steps.append(_result_step("install_play", install_result, install_command))
    if install_result.returncode != 0:
        return _finish_report(plan, run_id, started, steps, status="blocked", runner=runner)

    installed_source = Path(os.environ.get("PLAY_INSTALL_HOME", source)).expanduser()
    if os.environ.get("PLAY_INSTALL_HOME"):
        installed_source = installed_source.resolve() / "skill"
    else:
        data = Path(os.environ.get("XDG_DATA_HOME", _home() / ".local" / "share")).expanduser()
        installed_source = (data / "modiqo" / "play" / "skill").resolve()
    for harness in selected:
        steps.append(install_hooks(harness, installed_source, run_id=run_id))

    identity = _probe_identity(rote, runner)
    steps.append(
        Step(
            "rote_identity",
            "completed" if identity == "authenticated" else "human_action_required",
            "Rote identity verified." if identity == "authenticated" else "Run the rote-setup skill to sign in and finish optional API setup.",
        )
    )
    launcher = Path(
        os.environ.get("PLAY_MACHINE_LAUNCHER", _home() / ".local" / "bin" / "play-machine")
    ).expanduser()
    verification_path = os.pathsep.join(
        part for part in (str(launcher.parent), os.environ.get("PATH", "")) if part
    )
    for harness in selected:
        command = [
            "env",
            f"PATH={verification_path}",
            str(installed_source / "scripts" / "bin" / "play-preflight"),
            "--harness",
            harness,
            "--json",
        ]
        result = runner(command)
        steps.append(_result_step("verify", result, command))
    if any(step.status in {"failed", "approval_required"} for step in steps):
        status = "blocked"
    elif any(step.status in {"human_action_required", "review_required"} for step in steps):
        status = "action_required"
    else:
        status = "completed"
    return _finish_report(plan, run_id, started, steps, status=status, runner=runner)


def _finish_report(
    plan: dict[str, Any],
    run_id: str,
    started: str,
    steps: Sequence[Step],
    *,
    status: str,
    runner: Runner,
) -> dict[str, Any]:
    report = {
        "schema": REPORT_SCHEMA,
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "status": status,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "selected_harnesses": plan["selected_harnesses"],
        "targets": plan["targets"],
        "rote": {"before": plan["rote"], "after": _rote_snapshot(runner)},
        "rote_skills": {
            "before": plan["rote_skills"],
            "after": _rote_skills_snapshot(
                [
                    str(item["provider"])
                    for item in plan["rote_skills"]
                    if isinstance(item, dict) and item.get("provider") in ROTE_SKILL_PROVIDERS
                ]
            ),
        },
        "steps": [asdict(step) for step in steps],
        "restart": "Restart every selected running harness so it reloads skills and hooks.",
    }
    json_path, markdown_path = write_report(report)
    return {**report, "report_paths": {"json": str(json_path), "markdown": str(markdown_path)}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "install"):
        command = subparsers.add_parser(name)
        command.add_argument("--top-k", type=int, default=3)
        command.add_argument("--harness", action="append", choices=SUPPORTED_HARNESSES)
        command.add_argument("--json", action="store_true")
    apply_parser = subparsers.choices["apply"]
    apply_parser.add_argument("--approve-remote-installer", action="store_true")
    apply_parser.add_argument("--run-id")
    apply_parser.add_argument("--plan-id")
    install_parser = subparsers.choices["install"]
    install_parser.add_argument(
        "--yes",
        action="store_true",
        help="apply the displayed Play plan without its interactive confirmation",
    )
    install_parser.add_argument(
        "--approve-remote-installer",
        action="store_true",
        help="separately approve https://getrote.dev/install when Rote is missing",
    )
    install_parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            payload = build_plan(top_k=args.top_k, requested=args.harness)
        elif args.command == "apply":
            source = Path(__file__).resolve().parents[3]
            payload = apply(
                source,
                top_k=args.top_k,
                requested=args.harness,
                approve_remote_installer=args.approve_remote_installer,
                run_id=args.run_id,
                expected_plan_id=args.plan_id,
            )
        else:
            source = Path(__file__).resolve().parents[3]
            plan = build_plan(top_k=args.top_k, requested=args.harness)
            print(_render_plan(plan), file=sys.stderr if args.json else sys.stdout)
            if not args.yes and not _confirm(
                "Continue with this exact Play bootstrap plan?", default=True
            ):
                print("Play installation cancelled before any changes were made.")
                return 0
            approve_remote_installer = args.approve_remote_installer
            if plan["rote"]["path"] is None and not approve_remote_installer:
                approve_remote_installer = _confirm(
                    "Rote is missing. Run the official installer from "
                    "https://getrote.dev/install?",
                    default=False,
                )
            payload = apply(
                source,
                top_k=args.top_k,
                requested=args.harness,
                approve_remote_installer=approve_remote_installer,
                run_id=args.run_id,
                expected_plan_id=plan["plan_id"],
            )
    except (BootstrapError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"play-bootstrap: {error}\n")
    rendered = (
        _render_plan(payload)
        if args.command == "plan"
        else (_render_status_card(payload) if args.command == "install" else _markdown(payload))
    )
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else rendered)
    return 0 if payload.get("status", "completed") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
