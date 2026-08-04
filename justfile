check:
    scripts/bin/validate-machine
    scripts/bin/play-question choose_creator_path --harness codex --check
    scripts/bin/play-question choose_creator_path --harness claude --check
    scripts/bin/play-question choose_creator_path --harness kimi --check
    scripts/bin/play-question approve_play_run --harness codex --check
    scripts/bin/play-question approve_play_run --harness claude --check
    scripts/bin/play-question approve_play_run --harness kimi --check
    scripts/bin/play-question choose_search_result --harness codex --check
    scripts/bin/play-question choose_search_result --harness claude --check
    scripts/bin/play-question choose_search_result --harness kimi --check
    typos README.md SKILL.md agents references scripts tests justfile

test: check
    python3 -m unittest discover -s tests -p 'test_*.py'

# Activate Play as the implicit entrypoint and make installed rote skills explicit-only.
install:
    scripts/harness/play-profile install

# Confirm source-linked installs are current and valid, then remind the user to restart.
update:
    scripts/harness/play-profile install
    scripts/harness/play-profile verify
    @echo "Play source is live through installed symlinks; restart running harnesses to reload it."

# Show the exact roots and rote skills that install would change.
plan:
    PLAY_PROFILE_VERBOSE=1 scripts/harness/play-profile plan

# Remove Play and restore every rote skill's original activation metadata.
uninstall:
    scripts/harness/play-profile uninstall

status:
    scripts/harness/play-profile status

status-roots:
    PLAY_PROFILE_VERBOSE=1 scripts/harness/play-profile status

verify-profile:
    scripts/harness/play-profile verify

# Start a fresh harness process so it reloads the installed skill profile.
harness harness="codex":
    scripts/harness/start-harness {{harness}}

# Start Codex with compact responses and no reasoning-event rendering for this session.
harness-quiet:
    scripts/harness/start-harness --quiet codex

# Run a read-only prompt that must reach Play's no-match consent gate.
smoke harness="codex":
    scripts/harness/start-harness --smoke {{harness}}

# This may consume model credits in each installed supported harness.
smoke-all:
    scripts/harness/start-harness --smoke-all
