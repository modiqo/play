# Distribute Play for Mac through Rote releases

Release maintainers use this runbook to build, review, and distribute the native Mac app.
Start with the PR's **Play for Mac review** workflow artifact, or run `python3 apps/macos/build.py --dmg` locally.
That command produces a local review DMG; it does not publish anything.

The current app version is **0.1.2**, with Play **0.4.99** bundled.
Public distribution remains pending Developer ID signing, Apple notarization, and the acceptance checks below.
The signing implementation has mocked failure-path coverage; this workstation has no Developer ID identity for a live signing test.

## Keep the app in its own release channel

The existing Rote infrastructure provides the public release repository and download proxy.
Use those services with a separate app tag and immutable asset name.

| Item | Value |
| --- | --- |
| Source and review | `modiqo/play`, `apps/macos/` |
| Public artifact repository | `modiqo/rote-releases` |
| App tag, in both repositories | `play-mac-v0.1.2` |
| Artifact | `Play-for-Mac-0.1.2-universal.dmg` |
| Checksum | Artifact name plus `.sha256` |
| Build manifest | Artifact name plus `.json` |
| Versioned download after publication | `https://releases.getrote.dev/play-mac-v0.1.2/Play-for-Mac-0.1.2-universal.dmg` |
| Minimum OS | macOS 13 |
| Architectures | Apple Silicon and Intel, in one DMG |
| Review owner | `hubertp` |

The [release Worker route](https://github.com/modiqo/rote-releases-worker/blob/196fb09f78aaff773fb2121b102a9a9e79ce54c1/src/routes.js) proxies release paths to GitHub assets.
Its R2 routes currently support Node and Deno runtimes; this app uses the GitHub release path.
The proposed app URL is not live until a maintainer publishes its assets.

Always use `--latest=false` for app releases in `rote-releases`.
Keep this initial app release marked as a prerelease even after staging review.
Rote's updater must retain its existing CLI release as “latest.”
The `play-mac-` prefix also avoids the CLI's `v*` release-retention filter.
See the [existing Rote release workflow](https://github.com/modiqo/rote/blob/743f4f6fc97e58dcf6ecfbd57557d20e6e540136/.github/workflows/release.yml).

The app has its own version in `build.py` and build number in `Info.plist` generation.
The core Play `VERSION` follows the existing Play release process.
This PR includes installer fixes that require a separate core Play release before the stable CLI installer receives them.
The Mac app includes those fixes in its bundled Play source.

## 1. Review the build without release credentials

The PR workflow compiles both architectures and uploads a seven-day review artifact with its checksum and manifest.
It has read-only repository permissions and receives no signing or publication secrets.
Find the artifact under the PR's **Play for Mac review** check, then download and extract it.
Its manifest must say `"distribution": "local-review"`.
Do not place this build on the public download channel.

For a local source review, these commands run isolated tests and build the same review package:

```sh
uv run --frozen python -m unittest discover -s apps/macos -p 'test_*.py' -v
uv run --frozen python scripts/bin/package-plugin --check
python3 apps/macos/build.py --dmg
```

Expect passing desktop tests, a clean generated package, and a verified DMG under `apps/macos/dist/`.
The build also writes a SHA-256 file and a provenance manifest.
The backend tests mock account writes and installation; compiling a Universal app does not prove execution on both architectures.

Review [REVIEW.md](REVIEW.md) for existing repository test failures and the installation failure analysis.
Use [ACCEPTANCE.md](ACCEPTANCE.md) to record staging results against the exact source commit and artifact digest.

## 2. Prepare an authorized release Mac

Use a clean checkout of the reviewed, merged commit from `modiqo/play/main`.
Install Xcode command-line tools, Python 3, `uv` 0.11.16, Git, and GitHub CLI.
The build downloads pinned Python and uv runtimes and installs dependencies from `uv.lock` with hashes.

The release operator needs these credentials outside the repository:

| Credential | Required access |
| --- | --- |
| Developer ID Application certificate and private key | Modiqo Apple Developer team, installed in a local Keychain |
| `notarytool` Keychain profile | Authorized Modiqo notarization account or App Store Connect key |
| GitHub CLI identity | Create tags in `modiqo/play`; write releases in `modiqo/rote-releases` |
| Cloudflare credentials | Only needed for a later installer-site link change, not this artifact upload |

Use a dedicated release Mac or restricted signing runner.
Do not expose signing credentials to pull-request workflows or commit certificates, passwords, tokens, or Keychain exports.
Apple documents [credential profiles and notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).

These commands show available identities and open the interactive credential setup:

```sh
security find-identity -v -p codesigning
xcrun notarytool store-credentials modiqo-play-mac
```

Expect a Modiqo `Developer ID Application:` identity and a validated Keychain profile named `modiqo-play-mac`.
Enter credentials at the prompt. Do not copy credentials into PR comments or shell scripts.

## 3. Build and verify a notarized artifact

Close the review app before rebuilding its bundle.
Record the clean source commit, then build with the exact identity from the previous step:

```sh
git status --short
git rev-parse HEAD
python3 apps/macos/build.py --dmg \
  --identity 'Developer ID Application: YOUR LEGAL TEAM NAME (TEAMID)' \
  --notary-profile modiqo-play-mac
python3 apps/macos/release.py
```

The build rejects dirty source and incomplete signing arguments.
It signs nested executables and libraries, then the app, with secure timestamps and hardened runtime.
It submits the app archive, requires Apple's `Accepted` result, and staples the ticket to the app.
It then packages, signs, notarizes, and staples the DMG before computing its final checksum.
It requests no hardened-runtime exception entitlements.
Validate Python extension loading and the copied runtime on the release Macs before approving distribution.

The verifier mounts the delivered DMG read-only and checks its embedded app, Universal executable, tickets, Gatekeeper assessment, and source provenance.
Expect `"status": "ready-for-staging"`; this does not replace the acceptance checklist.
The JSON manifest must say `"distribution": "notarized"` and contain both Apple submission identifiers.

Apple requires a Developer ID certificate and hardened runtime for this distribution path.
See [Apple's distribution requirements](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

If Apple rejects a submission, retain `.build/notary-app.json` or `.build/notary-dmg.json` and inspect the submission log.
A timeout can leave processing active at Apple; check that submission before retrying.
Do not publish an artifact from a failed build or substitute the earlier review DMG.
Never strip quarantine or disable Gatekeeper as an acceptance workaround.

## 4. Stage the signed assets for review

Complete the source review before tagging. Replace the example version when releasing another app version.
These commands tag the reviewed Play source and record the existing CLI latest release:

```sh
MAC_VERSION=0.1.2
MAC_TAG="play-mac-v${MAC_VERSION}"
MAC_ARTIFACT="Play-for-Mac-${MAC_VERSION}-universal.dmg"
git tag -a "$MAC_TAG" -m "Play for Mac ${MAC_VERSION}"
git push origin "$MAC_TAG"
gh api repos/modiqo/rote-releases/releases/latest --jq .tag_name
```

Record the source SHA and CLI latest tag in the staging review.
Never move an existing app tag or overwrite assets with different bytes.
Use a new app version for a changed artifact.

Update [RELEASE_NOTES.md](RELEASE_NOTES.md) with the source SHA, checksum, and completed acceptance evidence.
The notes must state app-update behavior, supported systems, and any remaining limitations.
Create a draft prerelease in the existing public release repository:

```sh
RELEASES_COMMIT=$(gh api repos/modiqo/rote-releases/commits/main --jq .sha)
gh release create "$MAC_TAG" \
  --repo modiqo/rote-releases --target "$RELEASES_COMMIT" \
  --draft --prerelease --latest=false \
  --title "Play for Mac ${MAC_VERSION}" \
  --notes-file apps/macos/RELEASE_NOTES.md \
  "apps/macos/dist/${MAC_ARTIFACT}" \
  "apps/macos/dist/${MAC_ARTIFACT}.sha256" \
  "apps/macos/dist/${MAC_ARTIFACT}.json"
```

The tag in `rote-releases` identifies its release record; the manifest identifies the actual Play source commit.
Draft assets require repository access and do not resolve through the public CDN.
Give `hubertp` the draft release URL, source PR, checksum, and completed [acceptance record](ACCEPTANCE.md).
Do not post raw installation logs or credentials to Discord; use the app's sanitized support report.

## 5. Publish after staging acceptance

Publish the exact accepted draft as an app prerelease, then verify both download and checksum through the CDN:

```sh
gh release edit "$MAC_TAG" --repo modiqo/rote-releases \
  --draft=false --prerelease --latest=false
MAC_VERIFY_DIR=$(mktemp -d)
MAC_CDN="https://releases.getrote.dev/${MAC_TAG}"
curl --fail --location --retry 5 --retry-all-errors \
  "${MAC_CDN}/${MAC_ARTIFACT}" -o "${MAC_VERIFY_DIR}/${MAC_ARTIFACT}"
curl --fail --location --retry 5 --retry-all-errors \
  "${MAC_CDN}/${MAC_ARTIFACT}.sha256" -o "${MAC_VERIFY_DIR}/${MAC_ARTIFACT}.sha256"
(cd "$MAC_VERIFY_DIR" && shasum -a 256 -c "${MAC_ARTIFACT}.sha256")
cmp "apps/macos/dist/${MAC_ARTIFACT}" "${MAC_VERIFY_DIR}/${MAC_ARTIFACT}"
gh api repos/modiqo/rote-releases/releases/latest --jq .tag_name
```

Expect an `OK` checksum, identical bytes, and the same CLI latest tag recorded before publication.
Test a browser download on clean Apple Silicon and Intel Macs; Gatekeeper must allow normal launch without a bypass.
Preserve the CDN result, Apple submission IDs, source SHA, digest, and reviewer sign-off in the release record.

The versioned proxy route needs no Cloudflare deployment.
If a maintainer adds a stable download link at `getrote.dev/playoffs/mac`, treat that as a separate `rote-releases` change.
Point it at this verified versioned URL with an uncached redirect.
The Pages project is `getrote-dev`; it requires an explicit deployment of the complete reviewed installer-site tree.
The website can then link to that route in its own reviewed change.
Do not replace `getrote.dev/install`, `/install.sh`, or `/playoffs/install.sh` with a DMG response.
This PR changes only the Play repository.

## 6. Withdraw a bad app release without changing Rote

Stop promoting the failing version and restore the download link to the previous accepted app version.
Mark the affected release as draft and retain its source, checksums, and diagnostics for investigation:

```sh
gh release edit "$MAC_TAG" --repo modiqo/rote-releases --draft --latest=false
```

This hides the release at GitHub. Cloudflare may retain cached bytes; a maintainer must purge the affected artifact URLs.
Coordinate that purge with the release Worker owner and verify that public downloads no longer serve the withdrawn artifact.
Do not delete tags, replace immutable files, or change the CLI's latest release.

The Mac app does not update itself automatically.
Users replace it with an accepted DMG; its Update action updates Play and Rote in the installed harnesses.
Play installation can restore its previous configuration after verification failure; Rote updates remain forward-only.
