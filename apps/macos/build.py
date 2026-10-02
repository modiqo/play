#!/usr/bin/env python3
"""Build a Universal Mac app for local review or notarized distribution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BUILD = HERE / ".build"
DIST = HERE / "dist"
APP_VERSION = "0.1.2"
PYTHON = "3.11.15"
UV = "0.11.16"
ARCHES = {"arm64": "aarch64", "x86_64": "x86_64"}
UV_SHA = {
    "arm64": "2b25be1af546be330b340b0a76b99f989daa6d92678fdffb87438e661e9d88fb",
    "x86_64": "6b91ae3de155f51bd1f5b74814821c79f016a176561f252cd9ddfb976939af2e",
}


def run(*args, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run([str(a) for a in args], cwd=ROOT, **kwargs)


def runtimes(resources):
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("Building requires uv. End users receive a bundled runtime.")
    run(uv, "python", "install", "--no-bin", "--install-dir", BUILD / "python",
        *[f"{PYTHON}-macos-{arch}-none" for arch in ARCHES.values()])
    requirements = BUILD / "requirements.txt"
    run(uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--output-file", requirements, stdout=subprocess.DEVNULL)
    lock_hash = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    for architecture, triple in ARCHES.items():
        cached = BUILD / "runtime" / architecture
        stamp = {"python": PYTHON, "uv": UV, "uv_sha256": UV_SHA[architecture],
                 "architecture": architecture, "lock_sha256": lock_hash}
        if not (cached / "runtime.json").is_file() or json.loads((cached / "runtime.json").read_text()) != stamp:
            if cached.exists():
                shutil.rmtree(cached)
            cached.mkdir(parents=True)
            shutil.copytree(BUILD / "python" / f"cpython-{PYTHON}-macos-{triple}-none", cached / "python", symlinks=True)
            run(uv, "pip", "sync", requirements, "--require-hashes", "--no-build",
                "--python-version", "3.11", "--python-platform", f"{triple}-apple-darwin",
                "--target", cached / "python/lib/python3.11/site-packages")
            archive = BUILD / f"uv-{triple}.tar.gz"
            if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != UV_SHA[architecture]:
                urllib.request.urlretrieve(f"https://github.com/astral-sh/uv/releases/download/{UV}/uv-{triple}-apple-darwin.tar.gz", archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != UV_SHA[architecture]:
                raise SystemExit("uv download failed SHA-256 verification")
            (cached / "bin").mkdir()
            with tarfile.open(archive) as bundle:
                for binary in ("uv", "uvx"):
                    source = bundle.extractfile(f"uv-{triple}-apple-darwin/{binary}")
                    if source is None:
                        raise SystemExit("uv archive is missing a binary")
                    with source, (cached / "bin" / binary).open("wb") as target:
                        shutil.copyfileobj(source, target)
                    (cached / "bin" / binary).chmod(0o755)
            (cached / "runtime.json").write_text(json.dumps(stamp, sort_keys=True) + "\n")
        shutil.copytree(cached, resources / "runtime" / architecture, symlinks=True)


def source_payload(destination):
    # Explicit tracked-file inventory prevents credentials, local state, and this app
    # (including its large runtimes) from entering Play's portable installation.
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for name in files:
        if not name or Path(name).parts[0] in {"apps", "tests", ".github"}:
            continue
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def sign(app, identity=None):
    options = ["--timestamp", "--options", "runtime"] if identity else []
    magic = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
    for path in sorted(app.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                macho = stream.read(4) in magic
            if macho:
                run("codesign", "--force", "--sign", identity or "-", *options, path, stdout=subprocess.DEVNULL)
    run("codesign", "--force", "--sign", identity or "-", *options, app)
    run("codesign", "--verify", "--deep", "--strict", app)


def notarize(archive, profile, receipt):
    result = run("xcrun", "notarytool", "submit", archive, "--keychain-profile", profile,
                 "--wait", "--timeout", "30m", "--output-format", "json", capture_output=True, text=True, check=False)
    receipt.write_text(result.stdout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"Notarization returned no valid receipt; inspect {receipt} and the Keychain profile") from error
    receipt.write_text(json.dumps(payload, indent=2) + "\n")
    if result.returncode != 0 or payload.get("status") != "Accepted" or not payload.get("id"):
        raise SystemExit(f"Notarization was not accepted; inspect {receipt}")
    return payload["id"]


def validate_distribution_args(parser, args):
    if bool(args.identity) != bool(args.notary_profile):
        parser.error("--identity and --notary-profile must be supplied together")
    if args.identity and (not args.dmg or not args.identity.startswith("Developer ID Application:")):
        parser.error("Distribution requires --dmg and a Developer ID Application identity")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dmg", action="store_true", help="Also create a compressed DMG")
    parser.add_argument("--identity", help="Developer ID Application identity; requires notarization")
    parser.add_argument("--notary-profile", help="Existing notarytool Keychain profile; no credentials in source")
    args = parser.parse_args()
    validate_distribution_args(parser, args)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    if args.identity and dirty:
        parser.error("Distribution builds require a clean source checkout")
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    if args.dmg:
        for suffix in (".json", ".sha256"):
            (DIST / f"Play-for-Mac-{APP_VERSION}-universal.dmg{suffix}").unlink(missing_ok=True)
    app = DIST / "Play for Mac.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    resources = contents / "Resources"
    binary = contents / "MacOS/Play"
    resources.mkdir(parents=True)
    binary.parent.mkdir()
    for source in (HERE / "Resources").iterdir():
        if source.is_dir():
            shutil.copytree(source, resources / source.name)
        else:
            shutil.copy2(source, resources / source.name)
    shutil.copy2(HERE / "backend.py", resources / "backend.py")
    source_payload(resources / "play-source")
    runtimes(resources)
    sources = sorted((HERE / "Sources").glob("*.swift"))
    sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    for architecture in ARCHES:
        run("xcrun", "swiftc", "-swift-version", "5", "-O", "-sdk", sdk,
            "-target", f"{architecture}-apple-macosx13.0", "-o", BUILD / f"Play-{architecture}", *sources)
    run("lipo", "-create", *[BUILD / f"Play-{arch}" for arch in ARCHES], "-output", binary)
    iconset = BUILD / "Play.iconset"
    iconset.mkdir(exist_ok=True)
    run("xcrun", "swift", HERE / "tools/Icon.swift", HERE / "Resources/modiqo-logo.png", BUILD / "icon.png")
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
            run("sips", "-z", size * scale, size * scale, BUILD / "icon.png", "--out", iconset / name, stdout=subprocess.DEVNULL)
    run("iconutil", "-c", "icns", iconset, "-o", resources / "Play.icns")
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": "ai.modiqo.play", "CFBundleName": "Play for Mac", "CFBundleDisplayName": "Play for Mac",
                      "CFBundleExecutable": "Play", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": APP_VERSION,
                      "CFBundleVersion": "3", "CFBundleIconFile": "Play", "LSMinimumSystemVersion": "13.0",
                      "LSApplicationCategoryType": "public.app-category.productivity", "NSHighResolutionCapable": True,
                      "NSPrincipalClass": "NSApplication", "NSHumanReadableCopyright": "© 2026 Modiqo"}, stream)
    sign(app, args.identity)
    notarization = {}
    if args.identity:
        archive = BUILD / "Play-notarization.zip"
        archive.unlink(missing_ok=True)
        run("ditto", "-c", "-k", "--keepParent", app, archive)
        notarization["app"] = notarize(archive, args.notary_profile, BUILD / "notary-app.json")
        run("xcrun", "stapler", "staple", app)
        run("xcrun", "stapler", "validate", app)
        run("spctl", "--assess", "--type", "execute", "--verbose=2", app)
    print(f"Built {app}", flush=True)
    if args.dmg:
        staging = BUILD / "dmg"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        notice = ("Developer ID signed and notarized by Apple.\n" if args.identity else
                  "Local review build: ad hoc signed, not Developer ID signed or notarized.\nUse only for local testing. Public distribution is not ready.\n")
        (staging / "Read me.txt").write_text(f"Play for Mac {APP_VERSION}\n\nDrag Play for Mac into Applications, then open it.\nApple Silicon and Intel; macOS 13 or newer.\n\n{notice}")
        dmg = DIST / f"Play-for-Mac-{APP_VERSION}-universal.dmg"
        manifest = DIST / f"{dmg.name}.json"
        checksum = DIST / f"{dmg.name}.sha256"
        # A failed build must not leave an old publication manifest/checksum.
        manifest.unlink(missing_ok=True)
        checksum.unlink(missing_ok=True)
        run("hdiutil", "create", "-ov", "-volname", "Play for Mac", "-srcfolder", staging, "-format", "UDZO", dmg)
        if args.identity:
            run("codesign", "--force", "--sign", args.identity, "--timestamp", dmg)
            notarization["dmg"] = notarize(dmg, args.notary_profile, BUILD / "notary-dmg.json")
            run("xcrun", "stapler", "staple", dmg)
            run("xcrun", "stapler", "validate", dmg)
            run("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=2", dmg)
        run("hdiutil", "verify", dmg)
        digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
        checksum.write_text(digest + "  " + dmg.name + "\n")
        manifest.write_text(json.dumps({"schema_version": 1, "app_version": APP_VERSION,
            "play_version": (ROOT / "VERSION").read_text().strip(), "source_commit": revision,
            "source_dirty": dirty, "architectures": list(ARCHES), "minimum_macos": "13.0",
            "distribution": "notarized" if args.identity else "local-review",
            "artifact": dmg.name, "sha256": digest, "size": dmg.stat().st_size,
            "notarization": notarization}, indent=2) + "\n")
        print(f"Built {dmg}", flush=True)


if __name__ == "__main__":
    main()
