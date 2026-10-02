# Build Play for Mac

Play for Mac is a native onboarding and discovery app for people using Play in supported Mac harnesses.
Run `python3 apps/macos/build.py --dmg` from this repository to build the app and a Universal DMG.
The build creates both artifacts under `apps/macos/dist/`.

This is a local review build, version 0.1.2, with Play 0.4.99 bundled.
It targets macOS 13 or newer on Apple Silicon and Intel.
The default build is ad hoc signed for review.
The distribution build supports Developer ID signing and Apple notarization; live signing and clean-machine acceptance remain pending.
Follow [DISTRIBUTION.md](DISTRIBUTION.md) for Rote release channels, credentials, signing, staging, publication, and withdrawal.
Record release acceptance in [ACCEPTANCE.md](ACCEPTANCE.md).

## Build the app locally

Building requires macOS, Xcode with its command-line tools, Python 3, `uv`, Git, and internet access.
End users receive bundled Python and `uv` runtimes for both architectures.

1. Run the bridge tests from the Play repository:

   ```sh
   uv run python -m unittest discover -s apps/macos -p 'test_*.py' -v
   ```

   The tests cover authentication boundaries, archive validation, installation review, recovery receipts, search, and durable runtimes.
   They use mocked commands for authentication, invitations, and installation.

2. Build the app and DMG:

   ```sh
   python3 apps/macos/build.py --dmg
   ```

   The build compiles both architectures, bundles locked Python dependencies, verifies the app signature, and checks the DMG.
   It also writes a SHA-256 file beside the DMG.
   Omit `--dmg` when only rebuilding the app.

3. Open `apps/macos/dist/Play for Mac.app` in Finder.

   The app detects existing Play, Rote, and harness installations.
   An existing Rote sign-in opens Home; new users start setup.
   Installations and updates require reviewing a plan and choosing its install button.

## Review the user flow

- Prepare missing Rote, or update an older Rote before email sign-in.
- Sign in through Google, GitHub, or an email code using Rote’s existing interfaces.
- Optionally create an organization and invite colleagues as admins, developers, or readers.
- Select detected harnesses, review installation effects, and install Play with the existing bootstrap transaction.
- Review installed harnesses and versions on Home. Copy a starter prompt or an `/play explore` example.
- Search published Plays through the shared Worker. Results retain community, personal, and organization groups and relevance labels.
- Check for Play and Rote updates together. The app blocks Play downgrades and preserves Rote’s forward-only update behavior.

The toolbar provides System, Light, and Dark appearance choices that persist between launches.
The interface uses native SF Pro text and SF Mono for commands and versions.

The top organization link opens `https://www.modiqo.ai/account`.
Community, Playmakers, Trending, Documentation, and the Playoffs guide open in the browser.
Website sign-in remains separate from the native app’s Rote identity.

## Check the release boundaries

The native code and bridge live under `apps/macos` in the Play repository.
The app’s build excludes desktop assets from its bundled Play source.
The bridge delegates authentication, organization actions, and invitations to installed Rote commands.
It imports Play’s existing installer and search modules from the bundled or selected release.
It never indexes unpublished local Plays or runs a copied Play prompt automatically.

The app exchanges JSON with a child process over private pipes; it opens no local HTTP service.
Email codes travel through stdin and never enter command arguments or persisted app state.
Rote owns credentials. The app stores installation plans, receipts, and email-attempt metadata with private filesystem permissions.

Installation copies its bundled runtime into Application Support before creating Play environments.
Those environments continue to work after moving the app or ejecting the DMG.

Play installation uses the existing backup, verification, and automatic rollback behavior.
Rote updates happen before Play verification and cannot be rolled back by this app.
An interrupted installation stays visible at the next launch; the user reviews a fresh plan before retrying.
Successful installation returns to Home. A verified rollback also returns to Home with the failure and recovery status visible.
The Support button previews a report containing versions, the run identifier, affected harnesses, and curated error descriptions.
Users can copy that report and open the website’s Modiqo Discord invite to paste it themselves.
The app excludes credentials, account details, arbitrary paths, and raw logs from that report.

Updates download stable Play releases from the official GitHub repository over HTTPS.
The bridge validates archive paths, sizes, types, and version metadata before using the release.
Downloads have checksum receipts; they do not yet have an independently signed update manifest.
Mac application updates require downloading a new app build.

Before public distribution, test fresh installation and authenticated writes with disposable accounts on both physical architectures.
Also complete Developer ID signing, hardened-runtime validation, notarization, and Gatekeeper testing on a downloaded DMG.
The packaging script defaults to a local review build.
The distribution runbook documents the separate notarized build and verification commands.

Python and package licenses remain in their runtime directories.
The app includes `uv` licenses under `Resources/ThirdParty`.
The approved browser prototype remains in `prototype/` as a design reference.
