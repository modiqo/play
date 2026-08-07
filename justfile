check: package-check
    scripts/bin/validate-machine
    uv run scripts/bin/play-machine describe --json
    uv run pyright scripts/lib/play/controller.py scripts/lib/play/elicitation.py scripts/lib/play/onboarding.py scripts/lib/play/public_owner.py scripts/lib/play/public_trends.py scripts/lib/play/run_output.py scripts/lib/play/publication.py scripts/lib/play/publication_gate.py scripts/lib/play/certificate.py scripts/bin/play-machine scripts/bin/play-onboarding scripts/bin/play-public-trends scripts/bin/play-public-owner scripts/bin/play-run-output scripts/bin/play-publication scripts/bin/play-publication-gate scripts/bin/play-certificate tests/controller/test_controller_runtime.py tests/awareness/test_public_trends.py tests/foundation/test_elicitation.py tests/foundation/test_onboarding.py tests/foundation/test_public_owner.py tests/foundation/test_run_output.py tests/foundation/test_publication.py tests/foundation/test_publication_gate.py tests/foundation/test_certificate.py
    scripts/bin/play-question choose_creator_path --harness codex --check
    scripts/bin/play-question choose_creator_path --harness claude --check
    scripts/bin/play-question choose_creator_path --harness kimi --check
    scripts/bin/play-question approve_play_run --harness codex --check
    scripts/bin/play-question approve_play_run --harness claude --check
    scripts/bin/play-question approve_play_run --harness kimi --check
    scripts/bin/play-question choose_search_result --harness codex --check
    scripts/bin/play-question choose_search_result --harness claude --check
    scripts/bin/play-question choose_search_result --harness kimi --check
    scripts/bin/play-question private_public_or_skip --harness codex --context-json '{"publication":{"owner_summary":"Your claimed handle is ready."}}' --check
    scripts/bin/play-question private_public_or_skip --harness claude --context-json '{"publication":{"owner_summary":"Your claimed handle is ready."}}' --check
    scripts/bin/play-question private_public_or_skip --harness kimi --context-json '{"publication":{"owner_summary":"Your claimed handle is ready."}}' --check
    scripts/bin/play-question select_public_owner --harness codex --context-json '{"publication":{"owner_summary":"Your claimed handle is ready.","owner_choices":[{"id":"profile:chetan","owner":"chetan","display_name":"@chetan","ownership_description":"Use the claimed handle.","recommended":true}]}}' --check
    scripts/bin/play-question select_public_owner --harness claude --context-json '{"publication":{"owner_summary":"Your claimed handle is ready.","owner_choices":[{"id":"profile:chetan","owner":"chetan","display_name":"@chetan","ownership_description":"Use the claimed handle.","recommended":true}]}}' --check
    scripts/bin/play-question select_public_owner --harness kimi --context-json '{"publication":{"owner_summary":"Your claimed handle is ready.","owner_choices":[{"id":"profile:chetan","owner":"chetan","display_name":"@chetan","ownership_description":"Use the claimed handle.","recommended":true}]}}' --check
    scripts/bin/play-question welcome_play_request --harness codex --context-json '{"onboarding":{"email_handle":"friend"}}' --check
    scripts/bin/play-question welcome_play_request --harness claude --context-json '{"onboarding":{"email_handle":"friend"}}' --check
    scripts/bin/play-question welcome_play_request --harness kimi --context-json '{"onboarding":{"email_handle":"friend"}}' --check
    typos README.md SKILL.md agents references scripts tests justfile

# Generate the self-contained marketplace skill from this repository's source of truth.
package:
    scripts/bin/package-plugin

# Fail when the marketplace payload omits or drifts from runtime/configuration source files.
package-check:
    scripts/bin/package-plugin --check

# Confirm that Rote is installed, authenticated, and exposes the Play runtime.
preflight harness="generic":
    scripts/bin/play-preflight --harness {{harness}}

# Install the optional React host adapter and its pinned thinking-orbs dependency.
ui-install:
    npm --prefix ui/thinking-orbs ci

# Type-check the optional thinking-orbs adapter.
ui-check:
    npm --prefix ui/thinking-orbs run typecheck

test: check
    uv run python3 -m unittest discover -s tests -p 'test_*.py'

# Measure warm typed-controller transition latency without model or external I/O.
benchmark-controller iterations="1000":
    uv run scripts/bin/play-machine benchmark --iterations {{iterations}} --json

# Activate or safely converge Play-first metadata after harness/Rote skill updates.
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
