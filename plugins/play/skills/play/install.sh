#!/bin/sh
set -eu

umask 077

fail() {
  printf '%s\n' "play install: $*" >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || fail "python3 is required"

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
  printf '%s\n' "◐ Downloading Play from $repository@$reference"
  curl --proto '=https' --tlsv1.2 -fsSL "$archive_url" -o "$archive"
  printf '%s\n' "✓ Downloaded Play"
  mkdir "$source_root"
  printf '%s\n' "◐ Verifying Play archive"
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
  printf '%s\n' "✓ Verified Play archive"
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

python3 "$source_root/scripts/bin/play-bootstrap" install "$@"
