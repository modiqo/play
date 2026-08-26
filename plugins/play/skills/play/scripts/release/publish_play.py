"""Publish the current Play tag through the stable Cloudflare Pages selector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASES_REPO = ROOT.parent / "rote-releases"
PUBLIC_SELECTOR = "https://getrote.dev/playoffs/install.sh"
PAGES_PROJECT = "getrote-dev"
SELECTOR_RELATIVE = Path("playoffs/install.sh")
VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SELECTOR_PATTERN = re.compile(r"(?m)^release=(v[0-9]+\.[0-9]+\.[0-9]+)$")


class ReleaseError(RuntimeError):
    """Raised when a release precondition or verification fails."""


def run(command: Sequence[str], *, cwd: Path) -> str:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise ReleaseError(f"{' '.join(command)}: {detail}")
    return result.stdout.strip()


def git(repository: Path, *arguments: str) -> str:
    return run(("git", *arguments), cwd=repository)


def release_tag(version_text: str) -> str:
    version = version_text.strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseError(f"VERSION must be semantic x.y.z; found {version!r}")
    return f"v{version}"


def selector_release(selector: str) -> str:
    matches = SELECTOR_PATTERN.findall(selector)
    if len(matches) != 1:
        raise ReleaseError("selector must contain exactly one semantic release assignment")
    return matches[0]


def replace_selector(selector: str, expected: str) -> str:
    current = selector_release(selector)
    if current == expected:
        return selector
    return SELECTOR_PATTERN.sub(f"release={expected}", selector, count=1)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "User-Agent": "modiqo-play-release/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeError, urllib.error.URLError) as error:
        raise ReleaseError(f"could not read {url}: {error}") from error


def require_clean_tracked(repository: Path) -> None:
    changed = git(repository, "status", "--porcelain", "--untracked-files=no")
    if changed:
        raise ReleaseError(f"tracked files are dirty in {repository}:\n{changed}")


def validate_play_release(play_root: Path) -> tuple[str, str]:
    version = (play_root / "VERSION").read_text(encoding="utf-8").strip()
    tag = release_tag(version)
    require_clean_tracked(play_root)
    if git(play_root, "branch", "--show-current") != "main":
        raise ReleaseError("Play release publication must run from main")
    git(play_root, "fetch", "origin", "main", "--tags")
    if git(play_root, "rev-parse", "HEAD") != git(play_root, "rev-parse", "origin/main"):
        raise ReleaseError("local Play main must match origin/main")
    run(("git", "merge-base", "--is-ancestor", tag, "origin/main"), cwd=play_root)
    tagged_version = git(play_root, "show", f"{tag}:VERSION").strip()
    if tagged_version != version:
        raise ReleaseError(f"{tag} contains VERSION {tagged_version}, expected {version}")
    remote_version = fetch_text(
        f"https://raw.githubusercontent.com/modiqo/play/{tag}/VERSION"
    ).strip()
    if remote_version != version:
        raise ReleaseError(
            f"GitHub {tag} contains VERSION {remote_version}, expected {version}"
        )
    return version, tag


def validate_releases_repo(repository: Path) -> Path:
    selector_path = repository / SELECTOR_RELATIVE
    if not selector_path.is_file():
        raise ReleaseError(f"missing selector: {selector_path}")
    require_clean_tracked(repository)
    if git(repository, "branch", "--show-current") != "main":
        raise ReleaseError("rote-releases publication must run from main")
    git(repository, "fetch", "origin", "main")
    if git(repository, "rev-parse", "HEAD") != git(repository, "rev-parse", "origin/main"):
        raise ReleaseError("local rote-releases main must match origin/main")
    return selector_path


def wait_for_public_selector(expected: str, *, timeout_seconds: int = 60) -> str:
    deadline = time.monotonic() + timeout_seconds
    last = "unavailable"
    while time.monotonic() < deadline:
        try:
            cache_buster = time.time_ns()
            body = fetch_text(f"{PUBLIC_SELECTOR}?release-check={cache_buster}")
            last = selector_release(body)
            if last == expected:
                return body
        except ReleaseError as error:
            last = str(error)
        time.sleep(2)
    raise ReleaseError(
        f"public selector did not reach {expected} within {timeout_seconds}s; found {last}"
    )


def check(play_root: Path) -> dict[str, object]:
    version, tag = validate_play_release(play_root)
    body = wait_for_public_selector(tag, timeout_seconds=10)
    return {
        "status": "ready",
        "version": version,
        "tag": tag,
        "public_selector": PUBLIC_SELECTOR,
        "selector_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def publish(play_root: Path, releases_repo: Path) -> dict[str, object]:
    version, tag = validate_play_release(play_root)
    selector_path = validate_releases_repo(releases_repo)
    if shutil.which("npx") is None:
        raise ReleaseError("npx is required to deploy the Cloudflare Pages project")
    original = selector_path.read_text(encoding="utf-8")
    updated = replace_selector(original, tag)
    changed = updated != original
    if changed:
        selector_path.write_text(updated, encoding="utf-8")
        run(("/bin/sh", "-n", str(selector_path)), cwd=releases_repo)
        git(releases_repo, "add", str(SELECTOR_RELATIVE))
        git(
            releases_repo,
            "commit",
            "-m",
            f"release: select Play {tag}",
            "-m",
            "What changed\n- Point the stable Play installer at the new tag.\n\n"
            "Why\n- The public installer must select the released Play payload.\n\n"
            "How to verify\n1. Check the selector syntax.\n"
            "2. Confirm the public selector reports the new tag.",
        )
        git(releases_repo, "push", "origin", "main")
    selector_commit = git(releases_repo, "rev-parse", "HEAD")
    deployment = run(
        (
            "npx",
            "wrangler",
            "pages",
            "deploy",
            ".",
            "--project-name",
            PAGES_PROJECT,
            "--branch",
            "main",
            "--commit-hash",
            selector_commit,
            "--commit-message",
            f"release: select Play {tag}",
            "--commit-dirty=false",
        ),
        cwd=releases_repo,
    )
    wait_for_public_selector(tag)
    deployment_url_match = re.search(r"https://[a-z0-9]+\.getrote-dev\.pages\.dev", deployment)
    return {
        "status": "published",
        "version": version,
        "tag": tag,
        "selector_changed": changed,
        "selector_commit": selector_commit,
        "deployment_url": deployment_url_match.group(0) if deployment_url_match else None,
        "public_selector": PUBLIC_SELECTOR,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "publish"))
    parser.add_argument(
        "--release-repo",
        type=Path,
        default=Path(os.environ.get("PLAY_RELEASES_REPO", DEFAULT_RELEASES_REPO)),
    )
    args = parser.parse_args(argv)
    try:
        payload = (
            check(ROOT)
            if args.action == "check"
            else publish(ROOT, args.release_repo.expanduser().resolve())
        )
    except (OSError, ReleaseError) as error:
        parser.exit(1, f"play-release: {error}\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
