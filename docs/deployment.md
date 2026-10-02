# Deployment and releases

The [Deploy Play workflow](../.github/workflows/deploy.yml) publishes the installer selector:

| Environment | Trigger | Installer | Selected Play revision |
| --- | --- | --- | --- |
| Staging | Every push to `main`, including every merged PR | `https://stg.getrote.dev/playoffs/install.sh` | The triggering commit SHA; no version tag required |
| Production | A repository admin selects **Actions → Deploy Play → Run workflow → Tags → vX.Y.Z** | `https://getrote.dev/playoffs/install.sh` | The dispatched `vX.Y.Z` tag, which must match its `VERSION` |

Published changes must carry a new plugin version; a push that keeps the same version is not a
reliable cache invalidation mechanism. Prepare the version bump and package metadata changes on
a branch and merge them through a PR. After the PR is merged, create the release tag with:

```bash
just release-tag-check                # Preview the tag and commit without creating or pushing it.
just release-tag                      # Create and push the tag for freshly fetched origin/main.
# Or pin the merged commit explicitly:
just release-tag <merged-commit-sha>
```

The helper reads `VERSION` from the selected commit, derives `vX.Y.Z`, and requires that commit
to belong to `origin/main`. It works from any checkout branch and ignores uncommitted version
edits. It creates an annotated tag and pushes only that tag, without changing or pushing `main`.
An existing local or remote tag pointing elsewhere is rejected; a remote tag already pointing to
the selected commit returns `already_tagged`. A matching local tag can be pushed again after a
failed push. The helper never moves an existing tag or bumps versions itself. Tag publication
does not trigger production deployment; an admin still runs **Deploy Play** manually.

Production runs only from a release tag. A dispatch from a branch, including `main`, is skipped.
The deploy checks out the tag's commit and fails unless the tag name matches that commit's
`VERSION` and the commit belongs to `origin/main`. Dispatching an older tag redeploys that
release, which is how to roll back. GitHub runs the workflow file stored in the tag itself, so
only tags created after this rule was added can be deployed to production.

Both environments read the shared installer assets, change only the Play selector in a temporary
directory, and deploy to `getrote-dev` (`staging` for preview, `main` for production). They wait for
the selected environment's installer to serve the expected revision and record a JSON receipt in
the workflow summary. The selector's single `release=` line may hold the `latest` placeholder or a
pinned tag or commit; each deploy replaces it with the deployed tag or commit SHA. No commit or push is made to the shared assets repository.

Run the read-only production release gate at any time:

```bash
just release-check
```

The gate prints a `ready` JSON receipt only when the public installer selects the current Play tag.
To check staging from a clean checkout of a merged commit, run
`.github/release/publish-play check --environment staging`.
