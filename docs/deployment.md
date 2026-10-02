# Deployment and releases

The [Deploy Play workflow](../.github/workflows/deploy.yml) publishes the installer selector:

| Environment | Trigger | Installer | Selected Play revision |
| --- | --- | --- | --- |
| Staging | Every push to `main`, including every merged PR | `https://stg.getrote.dev/playoffs/install.sh` | The triggering commit SHA; no version tag required |
| Production | A repository admin selects **Actions → Deploy Play → Run workflow → Tags → vX.Y.Z** | `https://getrote.dev/playoffs/install.sh` | The dispatched `vX.Y.Z` tag, which must match its `VERSION` |

Published changes must carry a new plugin version; a push that keeps the same version is not a
reliable cache invalidation mechanism. Prepare the version bump and package metadata changes on
a branch and merge them through a PR.

The [Tag Play release workflow](../.github/workflows/tag-release.yml) runs on every push to `main`
and tags releases itself. It reads `VERSION` from the pushed commit and derives `vX.Y.Z`:

| Existing `vX.Y.Z` tag | Result |
| --- | --- |
| None | Creates an annotated tag on the pushed commit and pushes only that tag (`tagged`) |
| On the pushed commit | Nothing to do (`already_tagged`) |
| On an earlier `main` commit | `VERSION` did not change, so this push is not a release (`version_unchanged`) |
| On any other commit | Fails; the workflow never moves an existing tag |

Each run records its JSON receipt in the workflow summary. The workflow never bumps versions or
pushes `main`. Tag publication does not trigger production deployment; an admin still runs
**Deploy Play** manually from the new tag.

Production runs only from a release tag. A dispatch from a branch, including `main`, is skipped.
The deploy checks out the tag's commit and fails unless the tag name matches that commit's
`VERSION` and the commit belongs to `origin/main`. Dispatching an older tag redeploys that
release, which is how to roll back. GitHub runs the workflow file stored in the tag itself, so
only tags created after this rule was added can be deployed to production.

Both environments read the shared installer assets, change only the Play selector in a temporary
directory, and deploy to `getrote-dev` (`staging` for preview, `main` for production). They wait for
the selected environment's installer to serve the expected revision and record a JSON receipt in
the workflow summary. The selector's single `release=` line may hold the `latest` placeholder or a
pinned tag or commit; each deploy replaces it with the deployed tag or commit SHA. No commit or
push is made to the shared assets repository.

To confirm what an installer serves, run the read-only gate from a clean checkout of `main`:
`.github/release/publish-play check` for production, or add `--environment staging`. It prints a
`ready` JSON receipt only when the installer selects the checked-out release.
