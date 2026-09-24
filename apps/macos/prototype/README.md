# Play for Mac interaction prototype

A clickable Mac app concept for reviewing Play onboarding, installed harnesses, and updates.
Open `index.html` directly, or serve this directory on loopback for clipboard support.

This command serves the prototype at `http://127.0.0.1:4179`:

```sh
python3 -m http.server 4179 --bind 127.0.0.1 --directory apps/macos/prototype
```

Run the command from the Play repository root. This prototype has no build step or external dependencies.

## Review the complete setup

1. Choose **Try onboarding** in the prototype toolbar.
2. Switch between an existing installation and a fresh Mac.
3. Choose Google, GitHub, or email. Email verification uses the demo code `123456`.
4. Create a sample organization or skip this step.
5. Add sample colleagues as co-managers or members. No invitations are sent.
6. Choose detected harnesses and review the installation plan.
7. Run the simulated installation. Preview an interrupted download and retry the step.
8. Check the completion screen and Home for the installed harnesses.

Home also opens directly at `#home`. Other routes are `#search`, `#harnesses`, `#organizations`, `#updates`, and `#setup`.
The appearance control switches between light and dark modes. Command-K opens search.

## Existing installations get a paired update

The initial sample machine has Play 0.4.98 and Rote 0.84.0.
Home shows the available update to Play 0.4.99 and Rote 0.85.0.
The review includes both versions, selected harnesses, and a configuration backup.
After the simulation, Home and every harness show the updated versions.

The Updates screen can reset this sample state for another review.

The native implementation should compare installed versions with the release manifest.
It should select the Rote version required by that Play release.
Keep compatible existing versions. Never downgrade newer versions silently.

Verification must distinguish detection of a harness from a verified Play installation within that harness.

## The prototype uses explicit fixtures

Accounts, organizations, invitations, Plays, versions, and installation results are sample data.
Search filters the sample catalog locally. It does not call the search Worker.

The prototype does not inspect this Mac, authenticate, install software, or send invitations.
State resets when you reload the page.
Community, Playmakers, Trending, Documentation, and the field guide open the live Modiqo website.
The website may require a separate browser sign-in.

Only copying prompts and opening those public website links have effects outside the prototype.
Harness buttons preview the native handoff; they do not launch a harness or run a Play.

## Native implementation stays in Play

The intended production shell is SwiftUI, distributed as a signed, notarized Universal DMG for Apple Silicon and Intel.
This browser prototype reviews layout and behavior before native implementation.

| App responsibility | Existing source or proposed bridge |
| --- | --- |
| Harness labels and invocation commands | `scripts/lib/play/harnesses.py` |
| Detection, plan, backup, apply, verification | `scripts/lib/play/bootstrap.py` |
| Email code authentication | Existing Play email login adapter and released Rote OTP commands |
| Google and GitHub authentication | Released Rote browser login flow |
| Organization and invitation actions | Existing released organization commands, exposed through a Play-owned bridge |
| Authenticated search | `scripts/lib/play/search_transport.py` and the existing Cloudflare Worker |
| Progress and recoverable errors | Add structured events to the Play bridge; do not parse terminal output |
| Version checks and paired updates | Release metadata, existing installation plan, and verified distribution assets |

On a fresh Mac, prepare the verified runtime before asking Rote to authenticate.
Preserve the installation run ID across app restarts. Retry or restore through the existing backup mechanism.

Keep secrets out of URLs, UI logs, and progress events.
Query only published Plays. Group search results by community, personal account, and organization.
Use the shared search Worker for the native app; the local fixture filter is for this prototype only.

Keep organization owners separate from invited members in the account UI.

This prototype changes only the Play repository.

## Design references guide the interaction

These are design interpretations, not claims that one app is objectively the most beautiful.

| Reference | Direction used here |
| --- | --- |
| [Things](https://culturedcode.com/things/) | Calm spacing, readable tasks, and a focused next action |
| [Linear](https://linear.app/features) | Clear sidebar hierarchy and quiet status information |
| [Raycast](https://www.raycast.com/) | Keyboard access, search, and concise command handoffs |
| [The Playoffs](https://www.modiqo.ai/blog/the-playoffs) | An actionable introduction to finding, running, and creating Plays |

The prototype uses the unchanged Modiqo wordmark from the website asset `modiqo_mark.svg`.
Warm paper, muted green, and orange reference the website's current light theme.
Harness glyphs are illustrative identifiers from Play's harness definitions, not official third-party logos.

Production acceptance requires native accessibility checks and installer verification on both Apple Silicon and Intel.
This prototype does not validate signing, notarization, credentials, or production installation behavior.
