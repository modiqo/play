#!/bin/sh
set -eu

umask 077

fail() {
  printf '%s\n' "play install: $*" >&2
  exit 1
}

print_banner() {
  if [ "${PLAY_INSTALL_NO_BANNER:-0}" = 1 ]; then
    return
  fi
  if [ ! -t 1 ]; then
    printf '\n%s\n%s\n\n' 'Modiqo Rote' 'Where useful interactions become Plays—inspectable, composable, ready to run again.'
    return
  fi
  if [ -z "${NO_COLOR:-}" ]; then
    accent=$(printf '\033[38;5;141m')
    bright=$(printf '\033[1;97m')
    muted=$(printf '\033[38;5;245m')
    reset=$(printf '\033[0m')
  else
    accent=""
    bright=""
    muted=""
    reset=""
  fi
  printf '\n%s' "$accent"
  printf '%s\n' '  ███╗   ███╗  ██████╗  ██████╗  ██╗  ██████╗   ██████╗ '
  printf '%s\n' '  ████╗ ████║ ██╔═══██╗ ██╔══██╗ ██║ ██╔═══██╗ ██╔═══██╗'
  printf '%s\n' '  ██╔████╔██║ ██║   ██║ ██║  ██║ ██║ ██║   ██║ ██║   ██║'
  printf '%s\n' '  ██║╚██╔╝██║ ██║   ██║ ██║  ██║ ██║ ██║▄▄ ██║ ██║   ██║'
  printf '%s\n' '  ██║ ╚═╝ ██║ ╚██████╔╝ ██████╔╝ ██║ ╚██████╔╝ ╚██████╔╝'
  printf '%s\n' '  ╚═╝     ╚═╝  ╚═════╝  ╚═════╝  ╚═╝  ╚══▀▀═╝   ╚═════╝ '
  printf '%s%s%34s%s\n' "$reset" "$bright" 'R O T E' "$reset"
  printf '\n  %sWhere useful interactions become Plays—inspectable, composable, ready to run again.%s\n\n' "$muted" "$reset"
}

choose_install_mode() {
  install_mode=${PLAY_INSTALL_MODE:-}
  case "$install_mode" in
    guided|details) return ;;
    "") ;;
    *) fail "PLAY_INSTALL_MODE must be guided or details" ;;
  esac
  if [ "${PLAY_INSTALL_YES:-0}" = 1 ]; then
    install_mode=details
    return
  fi
  if [ ! -r /dev/tty ] || [ ! -w /dev/tty ]; then
    install_mode=guided
    return
  fi

  printf '%s\n' '  How would you like to set up?'
  printf '%s\n' '    [Enter] Guided setup    A quick walkthrough with one clear approval.'
  printf '%s\n' '    [d]     Review details  See every planned change before approval.'
  printf '%s' '  > ' > /dev/tty
  if ! IFS= read -r install_choice < /dev/tty; then
    fail "setup choice ended before a selection was received"
  fi
  case "$install_choice" in
    ""|g|G|guided) install_mode=guided ;;
    d|D|details) install_mode=details ;;
    n|N|q|Q|quit)
      printf '%s\n' 'Setup cancelled before any changes were made.'
      exit 0
      ;;
    *) fail "choose Enter for guided setup or d to review details" ;;
  esac
  printf '\n'
}

stage_start() {
  stage_label=$1
  if [ -t 2 ]; then
    printf '\r\033[2K◐ %s' "$stage_label" >&2
  else
    printf '%s\n' "◐ $stage_label" >&2
  fi
}

stage_finish() {
  if [ -t 2 ]; then
    printf '\r\033[2K✓ %s\n' "$stage_label" >&2
  else
    printf '%s\n' "✓ $stage_label" >&2
  fi
}

command -v python3 >/dev/null 2>&1 || fail "python3 is required"

print_banner
choose_install_mode

temporary=""
cleanup() {
  if [ -n "$temporary" ] && [ -d "$temporary" ]; then
    rm -rf "$temporary"
  fi
}
trap cleanup EXIT HUP INT TERM

if [ -n "${PLAY_INSTALL_SOURCE:-}" ]; then
  source_root=$PLAY_INSTALL_SOURCE
  printf '%s\n' "✓ Using local Play source"
else
  command -v curl >/dev/null 2>&1 || fail "curl is required"
  repository=${PLAY_INSTALL_REPOSITORY:-modiqo/play}
  reference=${PLAY_INSTALL_REF:-main}
  case "$repository" in
    *[!A-Za-z0-9._/-]*|/*|*/../*|../*|*/..) fail "invalid PLAY_INSTALL_REPOSITORY" ;;
  esac
  case "$reference" in
    *[!A-Za-z0-9._/-]*|/*|*/../*|../*|*/..) fail "invalid PLAY_INSTALL_REF" ;;
  esac
  temporary=$(mktemp -d "${TMPDIR:-/tmp}/play-install.XXXXXX")
  archive="$temporary/play.tar.gz"
  source_root="$temporary/source"
  archive_url=${PLAY_INSTALL_URL:-"https://github.com/$repository/archive/$reference.tar.gz"}
  case "$archive_url" in
    https://*) ;;
    *) fail "PLAY_INSTALL_URL must use https" ;;
  esac
  stage_start "Preparing Play from $repository@$reference"
  curl --proto '=https' --tlsv1.2 -fsSL "$archive_url" -o "$archive"
  mkdir "$source_root"
  python3 - "$archive" "$source_root" <<'PY'
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    roots = set()
    safe = []
    for member in members:
        parts = PurePosixPath(member.name).parts
        if not parts or member.name.startswith("/") or ".." in parts:
            raise SystemExit("play install: archive contains an unsafe path")
        roots.add(parts[0])
        if member.issym() or member.islnk() or member.isdev():
            raise SystemExit("play install: archive contains an unsupported entry")
        stripped = parts[1:]
        if not stripped:
            continue
        member.name = str(PurePosixPath(*stripped))
        safe.append(member)
    if len(roots) != 1:
        raise SystemExit("play install: archive must contain one repository root")
    # Python 3.14 requires callers to choose an extraction policy explicitly.
    # Older supported Python releases rely on the equivalent checks above.
    extract_options = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
    bundle.extractall(destination, members=safe, **extract_options)
PY
  stage_finish
fi

[ -f "$source_root/scripts/bin/play-bootstrap" ] || fail "downloaded Play package is incomplete"

case "${PLAY_INSTALL_YES:-}" in
  ""|0) ;;
  1) set -- "$@" --yes ;;
  *) fail "PLAY_INSTALL_YES must be 0 or 1" ;;
esac
case "${PLAY_APPROVE_REMOTE_INSTALLER:-}" in
  ""|0) ;;
  1) set -- "$@" --approve-remote-installer ;;
  *) fail "PLAY_APPROVE_REMOTE_INSTALLER must be 0 or 1" ;;
esac
if [ -n "${PLAY_INSTALL_TOP_K:-}" ]; then
  set -- "$@" --top-k "$PLAY_INSTALL_TOP_K"
fi
set -- "$@" --mode "$install_mode"

python3 "$source_root/scripts/bin/play-bootstrap" install "$@"
