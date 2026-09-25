#!/usr/bin/env python3
"""Verify a notarized build before a maintainer uploads it to Rote releases."""
from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess
from pathlib import Path

from build import APP_VERSION, DIST, ROOT


def validate_manifest(manifest, artifact, commit):
    if manifest.get("distribution") != "notarized" or manifest.get("source_dirty") is not False:
        raise ValueError("Only notarized builds from clean source can enter the release channel")
    if manifest.get("schema_version") != 1 or manifest.get("app_version") != APP_VERSION:
        raise ValueError("Manifest does not match the current Mac app version")
    if manifest.get("source_commit") != commit:
        raise ValueError("Checkout does not match the artifact source commit")
    if manifest.get("architectures") != ["arm64", "x86_64"] or manifest.get("minimum_macos") != "13.0":
        raise ValueError("Unexpected architecture or minimum macOS contract")
    if set(manifest.get("notarization", {})) != {"app", "dmg"} or not all(manifest["notarization"].values()):
        raise ValueError("Missing app or DMG notarization submission")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if (manifest.get("artifact") != artifact.name or manifest.get("sha256") != digest
            or manifest.get("size") != artifact.stat().st_size):
        raise ValueError("Artifact name, size, or SHA-256 does not match its manifest")
    return digest


def verify():
    def output(*command):
        return subprocess.check_output(command, cwd=ROOT, text=True).strip()

    if output("git", "status", "--porcelain"):
        raise ValueError("Release verification requires a clean checkout")
    commit = output("git", "rev-parse", "HEAD")
    dmg = DIST / f"Play-for-Mac-{APP_VERSION}-universal.dmg"
    manifest = json.loads(Path(str(dmg) + ".json").read_text())
    digest = validate_manifest(manifest, dmg, commit)
    if Path(str(dmg) + ".sha256").read_text().strip() != f"{digest}  {dmg.name}":
        raise ValueError("Checksum file does not match the artifact")
    if manifest.get("play_version") != (ROOT / "VERSION").read_text().strip():
        raise ValueError("Bundled Play version does not match source")
    # Inspect the app inside the actual deliverable, not an unrelated dist app.
    attached = plistlib.loads(subprocess.check_output([
        "hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(dmg)]))
    mount = next(Path(e["mount-point"]) for e in attached["system-entities"] if "mount-point" in e)
    try:
        app = mount / "Play for Mac.app"
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if info.get("CFBundleShortVersionString") != APP_VERSION or info.get("CFBundleIdentifier") != "ai.modiqo.play":
            raise ValueError("DMG contains an unexpected application")
        arches = set(output("lipo", "-archs", str(app / "Contents/MacOS/Play")).split())
        if arches != {"arm64", "x86_64"}:
            raise ValueError("Application is not Universal")
        for command in (
            ("codesign", "--verify", "--deep", "--strict", str(app)),
            ("xcrun", "stapler", "validate", str(app)),
            ("xcrun", "stapler", "validate", str(dmg)),
            ("spctl", "--assess", "--type", "execute", "--verbose=2", str(app)),
            ("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", str(dmg)),
        ):
            subprocess.run(command, check=True)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True)
    return {"status": "ready-for-staging", "source_commit": commit,
            "tag": f"play-mac-v{APP_VERSION}", "sha256": digest,
            "cdn_url": f"https://releases.getrote.dev/play-mac-v{APP_VERSION}/{dmg.name}"}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError, StopIteration) as error:
        raise SystemExit(f"Mac release verification failed: {error}") from error
