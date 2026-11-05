# Releases

`VERSION` is the only version to edit. On a branch, set it and run `just package`. That writes it
into the plugin manifests, `plugins/play/package.json`, `pyproject.toml`, and `uv.lock`, and
copies `SKILL.md` into the plugin. `just check` fails while any of them disagrees with `VERSION`.
Merge the bump through a PR.

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

Play has no installer of its own. rote's `install.sh --pack play` installs the journey pack that
rote pins in its `play` known pack.
