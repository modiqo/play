# Check spelling and the release scripts, and build the pack tarball.
check:
    typos README.md docs pack justfile .github
    python3 -m py_compile .github/release/tag_play.py .github/release/pack_tarball.py
    python3 .github/release/pack_tarball.py --output "$(mktemp -d)/play-pack.tar.gz" >/dev/null

# The rote binary the pack recipes run. Set ROTE to try a development build.
rote := env("ROTE", "rote")

# Each pack/transcripts/<name>.events.ron replays through `rote journey sim`
# and must produce <name>.trace.json. rote's `just play-compat` job runs the
# same checks against the pinned Play commit. Both pack recipes use a
# throwaway ROTE_HOME, so the real ~/.rote is never touched.
# Lint the journey pack and replay its transcripts.
pack-check:
    #!/usr/bin/env bash
    set -euo pipefail
    rote="$(command -v {{rote}})"
    sandbox="$(mktemp -d)"
    trap 'rm -rf "$sandbox"' EXIT
    export HOME="$sandbox/home" ROTE_HOME="$sandbox/home/.rote" NO_COLOR=1
    mkdir -p "$HOME"
    "$rote" config experimental set enabled true >/dev/null
    "$rote" journey pack lint pack
    "$rote" journey pack install pack --json >/dev/null
    failed=0
    for events in pack/transcripts/*.events.ron; do
      expected="${events%.events.ron}.trace.json"
      journey="$(jq -er .journey "$expected")"
      if diff -u --label "$expected" --label "rote journey sim $journey" \
          <(jq -S . "$expected") \
          <("$rote" journey sim "$journey" --events "$events" --json | jq -S .data.result); then
        echo "$events: trace matches"
      else
        echo "error: $events: trace differs from $expected" >&2
        failed=1
      fi
    done
    exit "$failed"

# A changed trace means rote now drives that path differently; review the diff.
# Rewrite each pack/transcripts/<name>.trace.json from `rote journey sim`.
pack-traces:
    #!/usr/bin/env bash
    set -euo pipefail
    rote="$(command -v {{rote}})"
    sandbox="$(mktemp -d)"
    trap 'rm -rf "$sandbox"' EXIT
    export HOME="$sandbox/home" ROTE_HOME="$sandbox/home/.rote" NO_COLOR=1
    mkdir -p "$HOME" "$sandbox/traces"
    "$rote" config experimental set enabled true >/dev/null
    "$rote" journey pack install pack --json >/dev/null
    # Write outside pack/ first: a new file there changes the installed digest.
    for events in pack/transcripts/*.events.ron; do
      name="$(basename "$events" .events.ron)"
      journey="$(sed -n 's/^ *journey: "\([^"]*\)".*/\1/p' "$events" | head -n 1)"
      "$rote" journey sim "$journey" --events "$events" --json | jq -e .data.result > "$sandbox/traces/$name.trace.json"
    done
    cp "$sandbox"/traces/*.trace.json pack/transcripts/
