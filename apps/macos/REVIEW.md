# Play for Mac 0.1.1 review

The local Universal app and DMG build successfully for Apple Silicon and Intel.
The native app has been opened and reviewed on Apple Silicon.
Physical Intel testing, Developer ID signing, and notarization remain outstanding.

## The installation failure had two causes

Python 3.11 defers directory enumeration until iteration.
Two installer helpers caught errors when creating the iterator, but not when reading it.
An absent optional harness directory therefore stopped activation.
Both helpers now enumerate inside their error handlers.
Read-only prerequisite checks now pass for the five harnesses in the failed installation.

The native bridge also tried to write a receipt that bootstrap had already saved.
That second write failed after installation or rollback, hiding the actual result.
The bridge now uses bootstrap’s receipt and recovers existing receipts when reopening after that error.
The user’s saved receipt confirms automatic restoration of the previous Play setup.

## Recovery and support remain visible

Successful installation returns to Home.
A confirmed rollback returns to Home with a persistent failure card.
Other failures keep recovery controls, including Go to Home, a local receipt, and support actions.
The Support sheet previews a copyable report with versions, affected harnesses, the run identifier, and curated error descriptions.
It omits credentials, account details, arbitrary local paths, and raw command output.
Discord buttons use the existing Modiqo website invite: `https://discord.gg/YyjBtzvhGz`.
The app never posts a support message automatically.

## Validation results

| Check | Result |
| --- | --- |
| Desktop regression tests, development Python | 27 passed |
| Desktop regression tests, bundled Python 3.11 | 27 passed |
| Activation-profile tests | 21 passed |
| Type checks for bridge, build script, and install-all | Passed |
| Generated Play package consistency | Passed |
| Universal compilation, signature verification, DMG checksum | Passed |
| Existing rollback recovered into Home | Verified in native UI |
| Support preview and Copy report | Verified in native UI |
| Community search | Live Worker results displayed |
| Accessible search with this Mac’s credential | Worker returned HTTP 401; sign-in recovery displayed |
| Fresh sign-in, new organization, invitations | Mocked tests; no live writes performed during QA |
| Retrying the full real installation after this fix | Pending user testing |

The broader repository run completed 855 tests with three failures.
All three reproduce from an unchanged archive of base commit `155b42c`.
Two concern degraded audit presentations; one is the warm-install timing threshold.
The installer subset likewise passes 24 of 25 tests, with that same timing failure.
The initial suspicion that Mac build artifacts caused the timing failure was incorrect.
No artifact-copy workaround remains in the installer.

The exploratory type check of `play-profile` also reports existing errors outside the changed directory helper.
That script is covered here by its 21 passing behavior tests and the lazy-iterator regression.

## Copy review

Route: desk row 4, documentation/how-to, with the AI-search overlay.
The README answers how to build and review Play for Mac across supported harnesses.
Its deterministic lint has zero failures. Full machine output remains in `.build/desk-readme.json`.
S-04 warnings concern verbs, lists, product names, and required technical terms; waived under clarity Law 1.
S-01 joins separate list items into one sentence; waived because the rendered items remain separate.
S-05 keeps the rollback subject explicit; the app is named as the actor that cannot reverse Rote updates.
Long implementation paragraphs preserve release conditions; waived under clarity Law 1.
Conservation: the README retains supported architectures, prerequisites, commands, effects, credential ownership, recovery, and release limitations.
Skim verdict: pass; the opening identifies the local build, followed by build steps, behavior, and distribution boundaries.
Extraction check: native app for Play; existing Rote authentication; published search with explicit access and relevance limits.
These claims match the implementation and preserve the Modiqo, Rote, and Play names.
Renderability: plain Markdown requires no JavaScript.
SPECULATIVE: this README should help developers evaluating cross-harness setup, but does not establish superiority over other onboarding apps.
Recommendation assessment is a single-model smoke test with shared bias, n=1, not a measurement.


## Native appearance review, 0.1.2

The app now uses neutral light and graphite dark palettes, thin panel borders, compact rectangular controls, and aligned harness rows.
SF Pro provides interface text; SF Mono distinguishes commands, versions, and counts.
The toolbar exposes persistent System, Light, and Dark appearance choices.
The Modiqo wordmark, organization link, installation recovery, and Discord support remain available.
Setup, search, organizations, updates, and support use the same shared components.

Both architecture builds compiled. The build verified the ad hoc app signature and the DMG checksum.
Native visual review covered dark Home, light Home with all four example prompts, light harness selection, and the dark support sheet.
The support sheet identifies app version 0.1.2 and retains the saved rollback report.
This appearance review performed no installation, sign-in, invitation, or organization write.
The earlier regression results and public distribution limitations above still apply.

Copy review: promotional headings were replaced with direct page labels; setup effects, recovery conditions, commands, and prompt examples were preserved.
The README appearance paragraph describes implemented controls. Technical names and separate list items retain the existing clarity waivers.


## Distribution handoff

The new review workflow builds a Universal DMG without publication credentials.
The distribution build requires a clean checkout, a Developer ID Application identity, and a notarytool Keychain profile.
It notarizes and staples both the app and DMG before writing the final checksum and manifest.
The release verifier mounts the actual DMG and checks its embedded application, source commit, signatures, tickets, and Gatekeeper results.
The Rote download proxy supports the separate `play-mac-v0.1.2` release namespace.
The runbook preserves the CLI latest release and documents staging, CDN verification, and withdrawal.

Local desktop tests now pass 30 cases, including release rejection and artifact-integrity gates.
Bridge, build, and release-verifier type checks report zero errors.
Generated skill consistency still passes for 176 files.
Live Developer ID signing, Apple submission, and clean-machine execution remain pending; this Mac has no signing identity.
No production upload or cross-repository modification forms part of this PR.


Distribution copy review: desk routes 1 (PR) and 4 (how-to/reference), with plain Markdown rendering.
The runbook preserves version, architecture, access, publication, and withdrawal conditions; the README retains its earlier behavior and limitations.
The new documentation has zero lint failures. Remaining S-04 technical-name warnings retain precision under Law 1.
S-01/T-02 warnings that combine rendered list items retain their separate steps under T-03; S-05 retains artifact-focused release states.
The skim follows review, signing, staging, publication, and withdrawal. Extraction matches the implemented app and existing Rote channels.
SPECULATIVE: the guide may help maintainers share Play across harnesses; this single-model smoke test has shared bias, n=1, and measures no discoverability gain.
