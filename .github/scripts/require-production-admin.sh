#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_EVENT_NAME:-}" != workflow_dispatch || "${GITHUB_REF:-}" != refs/heads/main ]]; then
  echo '::error::Production deployment requires a manual workflow dispatch from main.'
  exit 1
fi

# GITHUB_ACTOR retains the original actor on reruns; check the rerunner too.
# Any API failure, missing actor, or permission other than admin fails closed.
for actor in "${GITHUB_ACTOR:?}" "${GITHUB_TRIGGERING_ACTOR:?}"; do
  permission=$(gh api "repos/${GITHUB_REPOSITORY:?}/collaborators/$actor/permission" --jq '.permission')
  if [[ "$permission" != admin ]]; then
    echo "::error::Production deployment requires repository admin permission for $actor."
    exit 1
  fi
done
