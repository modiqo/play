check:
    scripts/validate-machine
    typos README.md SKILL.md agents references scripts tests justfile

test: check
    ruby tests/machine_conformance.rb
    python3 -m unittest discover -s tests -p '*_test.py'

# Activate Play as the implicit entrypoint and make installed rote skills explicit-only.
install:
    scripts/play-profile install

# Show the exact roots and rote skills that install would change.
plan:
    PLAY_PROFILE_VERBOSE=1 scripts/play-profile plan

# Remove Play and restore every rote skill's original activation metadata.
uninstall:
    scripts/play-profile uninstall

status:
    scripts/play-profile status

status-roots:
    PLAY_PROFILE_VERBOSE=1 scripts/play-profile status

verify-profile:
    scripts/play-profile verify

# Start a fresh harness process so it reloads the installed skill profile.
harness harness="codex":
    scripts/start-harness {{harness}}

# Run a read-only prompt that must reach Play's no-match consent gate.
smoke harness="codex":
    scripts/start-harness --smoke {{harness}}

# This may consume model credits in each installed supported harness.
smoke-all:
    scripts/start-harness --smoke-all
