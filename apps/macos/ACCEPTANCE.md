# Accept a Play for Mac release

The staging reviewer records results here or copies this checklist into the release review.
Use disposable accounts and isolated test Macs for account writes and installation cases.
Mark a check complete only after observing its result on the recorded artifact.

| Evidence | Value |
| --- | --- |
| App version | 0.1.2 |
| Play source commit | Pending |
| Final DMG SHA-256 | Pending |
| App and DMG Apple submission IDs | Pending |
| Apple Silicon Mac / macOS version | Pending |
| Intel Mac / macOS version | Pending |
| Reviewer and date | `hubertp` / pending |
| Decision | Pending; public release blocked |

## Verify the delivered application

- [ ] Download through a browser on both architectures; install through the Applications shortcut and launch normally.
- [ ] Confirm macOS 13 compatibility or raise the declared minimum before release.
- [ ] Confirm the app and both bundled runtimes report the expected versions and architectures.
- [ ] Eject the DMG and move the application; existing Play environments continue to work.
- [ ] Verify light, dark, and system appearances, keyboard navigation, narrow windows, and readable focus states.
- [ ] Confirm the downloaded checksum matches the accepted source manifest.
- [ ] Confirm Developer ID, hardened runtime, accepted notarization tickets, and Gatekeeper assessment.

## Exercise onboarding and existing installations

- [ ] Fresh setup detects missing Play/Rote and presents the installation plan before modifying the Mac.
- [ ] An existing setup opens Home and shows installed harnesses with their actual versions.
- [ ] Google, GitHub, and email code sign-in complete; invalid and expired codes show recovery controls.
- [ ] Create an organization, skip organization creation, and continue with an existing organization.
- [ ] Invite a test colleague, verify the intended role, and recover from an invitation error without duplicate sends.
- [ ] Check harness detection and initial selection against installed applications; unselected harnesses retain their configuration.
- [ ] Install selected harnesses, restart them, and verify that each recognizes Play.
- [ ] Complete a small Play from each supported harness being claimed for this release.
- [ ] Update Play and Rote through a reviewed plan; verify newer installed Play versions cannot be downgraded.

## Exercise failures and discovery

- [ ] Missing optional skill folders do not fail activation.
- [ ] Simulate a failed verification in an isolated setup; confirm restoration and Home's persistent failure details.
- [ ] Interrupt and reopen the app; confirm it reconciles the saved receipt rather than reporting false success.
- [ ] Confirm a successful installation returns to Home.
- [ ] Copy the support report; confirm it excludes account details, credentials, arbitrary paths, and raw logs.
- [ ] Open Discord support; confirm nothing posts automatically.
- [ ] Search public, personal, and organization scopes; confirm access restrictions, grouping, and uncertainty labels.
- [ ] Expire a test credential; confirm private search requires sign-in recovery.
- [ ] Confirm unpublished local Plays do not appear in search.
- [ ] Copy each real example; confirm the preferred harness command and that copying does not run the Play.
- [ ] Verify account, community, Playmakers, Trending, documentation, and Playoffs links.

## Accept publication evidence

- [ ] Record the draft release and source PR; all blocking checks above passed on both architectures.
- [ ] Confirm bundled runtime and package notices accompany the app.
- [ ] Confirm public CDN bytes match the reviewed, notarized DMG after publication.
- [ ] Confirm the app release stays a prerelease and does not replace the Rote CLI latest release.
- [ ] Record download-link ownership and the Cloudflare purge contact for withdrawal.

Known test limitations and earlier local evidence remain in [REVIEW.md](REVIEW.md).
The universal build and mocked tests alone do not satisfy this acceptance record.
