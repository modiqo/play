"""Build and verify the marketplace Play plugin: manifests plus a pointer to rote's Play skill."""

from __future__ import annotations

import argparse
import filecmp
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "plugins" / "play" / "skills" / "play"
INSTALLED_SKILL = "${ROTE_HOME:-$HOME/.rote}/play/current/SKILL.md"
ROTE_INSTALLER = "curl -fsSL https://getrote.dev/install | bash"
PLAY_INSTALL = "rote install play"
POINTER_BODY = f"""
# Play

This marketplace plugin is a pointer. Play is installed and updated through rote, which links the
real Play skill into this agent.

## Load the installed Play skill

If `{INSTALLED_SKILL}` exists, read it completely and follow it for
this request. It is the Play skill; resolve the bundled paths it names, such as `scripts/bin/...`,
against `${{ROTE_HOME:-$HOME/.rote}}/play/current`.

## When Play is not installed

If that file is missing, tell the user Play runs through rote and give them the install command:

- When `rote` is not on `PATH`: `{ROTE_INSTALLER}`, which installs rote
  and then Play.
- Otherwise: `{PLAY_INSTALL}`.

Tell them to restart the agent afterwards so it loads the installed skill. Never run either command
without the user's approval. Never copy Play's runtime files, rote's installation, credentials, or
tokens into this plugin or the agent's skill directories.
"""
# The source path of each packaged file except SKILL.md, which is the pointer.
COPIED_FILES = (Path("agents/openai.yaml"),)
VERSION_FILE = ROOT / "VERSION"
_JSON_VERSION = re.compile(r'(?m)^(  "version": ")([^"]*)(",?)$')
# Each file carries VERSION in exactly one place; packaging rewrites it from VERSION.
VERSIONED_FILES = {
    Path("plugins/play/.claude-plugin/plugin.json"): _JSON_VERSION,
    Path("plugins/play/.codex-plugin/plugin.json"): _JSON_VERSION,
    Path("plugins/play/.cursor-plugin/plugin.json"): _JSON_VERSION,
    Path("plugins/play/.kimi-plugin/plugin.json"): _JSON_VERSION,
    Path("plugins/play/package.json"): _JSON_VERSION,
    Path("pyproject.toml"): re.compile(r'(?m)^(version = ")([^"]*)(")$'),
    Path("uv.lock"): re.compile(
        r'(?m)^(\[\[package\]\]\nname = "modiqo-play-controller"\nversion = ")([^"]*)(")$'
    ),
}


class PackageError(RuntimeError):
    pass


def play_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise PackageError(f"VERSION must be semantic x.y.z; found {version!r}")
    return version


def versioned_text(relative: Path, version: str) -> tuple[str, str]:
    """Return the file's current version and its text rewritten to `version`."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    pattern = VERSIONED_FILES[relative]
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise PackageError(f"{relative} must contain exactly one version assignment")
    return matches[0][1], pattern.sub(lambda match: f"{match[1]}{version}{match[3]}", text, count=1)


def version_differences(version: str) -> list[str]:
    messages = []
    for relative in VERSIONED_FILES:
        current, _ = versioned_text(relative, version)
        if current != version:
            messages.append(f"version {relative} is {current}, expected {version} from VERSION")
    return messages


def sync_versions(version: str) -> None:
    for relative in VERSIONED_FILES:
        current, text = versioned_text(relative, version)
        if current != version:
            (ROOT / relative).write_text(text, encoding="utf-8")


def pointer_skill() -> str:
    """Root SKILL.md frontmatter, so discovery matches Play requests, over the pointer body."""
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    end = text.find("\n---\n", 4)
    if not text.startswith("---\n") or end < 0:
        raise PackageError("SKILL.md must open with YAML frontmatter")
    return text[: end + len("\n---\n")] + POINTER_BODY


def materialize(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "SKILL.md").write_text(pointer_skill(), encoding="utf-8")
    for relative in COPIED_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def differences(expected: Path, actual: Path) -> list[str]:
    expected_files = {
        path.relative_to(expected): path for path in expected.rglob("*") if path.is_file()
    }
    actual_files = {
        path.relative_to(actual): path for path in actual.rglob("*") if path.is_file()
    } if actual.is_dir() else {}
    messages = [f"missing {path}" for path in sorted(expected_files.keys() - actual_files.keys())]
    messages.extend(f"extra {path}" for path in sorted(actual_files.keys() - expected_files.keys()))
    for relative in sorted(expected_files.keys() & actual_files.keys()):
        expected_path = expected_files[relative]
        actual_path = actual_files[relative]
        if not filecmp.cmp(expected_path, actual_path, shallow=False):
            messages.append(f"stale {relative}")
        expected_exec = bool(stat.S_IMODE(expected_path.stat().st_mode) & stat.S_IXUSR)
        actual_exec = bool(stat.S_IMODE(actual_path.stat().st_mode) & stat.S_IXUSR)
        if expected_exec != actual_exec:
            messages.append(f"mode {relative}")
    return messages


def build(check: bool = False) -> None:
    version = play_version()
    if not check:
        sync_versions(version)
    with tempfile.TemporaryDirectory(prefix="play-plugin-") as temporary:
        expected = Path(temporary) / "play"
        materialize(expected)
        if check:
            found = version_differences(version) + differences(expected, TARGET)
            if found:
                raise PackageError("plugin pointer differs:\n  " + "\n  ".join(found))
            print(f"Play plugin pointer is current ({1 + len(COPIED_FILES)} files)")
            return
        if TARGET.exists():
            shutil.rmtree(TARGET)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(expected, TARGET, copy_function=shutil.copy2)
        print(f"Built Play plugin pointer at {TARGET} ({1 + len(COPIED_FILES)} files)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        build(check=args.check)
    except PackageError as error:
        parser.exit(1, f"package-plugin: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
