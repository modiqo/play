# Releases

`VERSION` is the only version to edit. Set it on a branch and merge the bump through a PR.

The [Tag Play release workflow](../.github/workflows/tag-release.yml) runs on every push to `main`
and tags releases itself. It reads `VERSION` from the pushed commit and derives `vX.Y.Z`:

| Existing `vX.Y.Z` tag | Result |
| --- | --- |
| None | Creates an annotated tag on the pushed commit and pushes only that tag (`tagged`) |
| On the pushed commit | Nothing to do (`already_tagged`) |
| On an earlier `main` commit | `VERSION` did not change, so this push is not a release (`version_unchanged`) |
| On any other commit | Fails; the workflow never moves an existing tag |

The workflow checks the tag first without creating or pushing it. The **Tag a new VERSION** step
runs only when the check reports `ready`; an existing tag produces a visibly skipped creation
step. The creation step checks again before pushing, so a tag created after the initial check is
also preserved.

Each run records its JSON receipt in the workflow summary, including skipped creation decisions.
The workflow never bumps versions or pushes `main`.

When the workflow creates a tag, it also publishes a GitHub release for it with one asset,
`play-pack.tar.gz`: the files of `pack/` with `pack.ron` at the root, built by
`.github/release/pack_tarball.py`. The same files always give the same bytes. rote's `play` known
pack pins that asset's URL, its SHA-256, and the digest it unpacks to, so moving the pin is a rote
PR that names the new tag.

Play has no installer of its own. rote's `install.sh --pack play` installs the pinned pack.
