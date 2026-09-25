"""Create and push the version tag for a commit already merged into origin/main."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .publish_play import ReleaseError, git, release_tag


ROOT = Path(__file__).resolve().parents[2]
MAIN_REF = "refs/remotes/origin/main"


def remote_tag_commit(repository: Path, remote: str, tag_ref: str) -> str | None:
    refs = {}
    for line in git(repository, "ls-remote", "--tags", remote, tag_ref, f"{tag_ref}^{{}}").splitlines():
        object_id, name = line.split()
        refs[name] = object_id
    # Annotated tags advertise their target separately from the tag object itself.
    return refs.get(f"{tag_ref}^{{}}", refs.get(tag_ref))


def tag_release(
    repository: Path, *, revision: str = "origin/main", dry_run: bool = False,
) -> dict[str, object]:
    git(repository, "fetch", "--no-tags", "origin", f"refs/heads/main:{MAIN_REF}")
    target = MAIN_REF if revision == "origin/main" else revision
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", f"{target}^{{commit}}")
    try:
        git(repository, "merge-base", "--is-ancestor", commit, MAIN_REF)
    except ReleaseError as error:
        raise ReleaseError(f"release commit {commit} must already belong to origin/main") from error

    version = git(repository, "show", f"{commit}:VERSION").strip()
    tag = release_tag(version)
    tag_ref = f"refs/tags/{tag}"
    local_object = git(repository, "tag", "--list", "--format=%(objectname)", tag)
    if local_object:
        local_commit = git(repository, "rev-parse", "--verify", f"{local_object}^{{commit}}")
        if local_commit != commit:
            raise ReleaseError(f"local {tag} points to {local_commit}, expected {commit}; refusing to move it")

    # Inspect the push destination, which may differ from origin's fetch URL.
    push_urls = git(repository, "remote", "get-url", "--push", "--all", "origin").splitlines()
    if len(push_urls) != 1:
        raise ReleaseError("origin must have exactly one push URL for release tagging")
    destination = push_urls[0]
    remote_commit = remote_tag_commit(repository, destination, tag_ref)
    if remote_commit is not None and remote_commit != commit:
        raise ReleaseError(f"remote {tag} points to {remote_commit}, expected {commit}; refusing to move it")

    receipt: dict[str, object] = {
        "status": "already_tagged" if remote_commit is not None else "ready",
        "version": version,
        "tag": tag,
        "commit": commit,
        "remote": "origin",
        "dry_run": dry_run,
    }
    if dry_run or remote_commit is not None:
        return receipt

    if not local_object:
        git(repository, "tag", "--annotate", tag, commit, "--message", f"Release Play {tag}")
        local_object = git(repository, "rev-parse", "--verify", tag_ref)

    # Pin the object and destination ref. Never push branches, other tags, or force updates,
    # even when the caller has configured push.followTags or remote.origin.push.
    git(repository, "push", "--no-follow-tags", destination, f"{local_object}:{tag_ref}")
    if remote_tag_commit(repository, destination, tag_ref) != commit:
        raise ReleaseError(f"remote {tag} did not resolve to {commit} after pushing")
    receipt["status"] = "tagged"
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="origin/main", help="merged commit or ref (default: origin/main)")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without creating or pushing a tag")
    args = parser.parse_args(argv)
    try:
        receipt = tag_release(ROOT, revision=args.commit, dry_run=args.dry_run)
    except (OSError, ReleaseError) as error:
        parser.exit(1, f"play-release-tag: {error}\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
