#!/bin/sh
# rote installs, updates, and repairs Play. This script only hands off to it:
#   no rote                     -> run rote's installer, which installs Play too
#   rote without `install play` -> `rote update`, then check again
#   otherwise                   -> rote install play "$@"
set -eu

rote_installer_url=https://getrote.dev/install

fail() {
  printf '%s\n' "play install: $*" >&2
  exit 1
}

# Commands below may prompt; when this script arrives on stdin (curl | sh),
# give them the terminal instead of the rest of the script.
run_with_terminal() {
  if (: </dev/tty) 2>/dev/null; then
    "$@" </dev/tty
  else
    "$@" </dev/null
  fi
}

rote_installs_play() {
  rote install play --help 2>/dev/null | grep -q -- '--from'
}

if ! command -v rote >/dev/null 2>&1; then
  command -v curl >/dev/null 2>&1 || fail "curl is required to install rote"
  printf '%s\n' "rote is not installed. Running its installer, which installs Play: curl -fsSL $rote_installer_url | bash" >&2
  curl -fsSL "$rote_installer_url" | bash
  exit 0
fi

if ! rote_installs_play; then
  printf '%s\n' "This rote cannot install Play yet. Running: rote update" >&2
  run_with_terminal rote update
  rote_installs_play || fail "rote update did not add \`rote install play\`; reinstall rote: curl -fsSL $rote_installer_url | bash"
fi

printf '%s\n' "Running: rote install play${*:+ $*}" >&2
run_with_terminal rote install play "$@"
