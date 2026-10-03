#!/usr/bin/env bash
# Install Bron on a Mac:
#   curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash
# Into a chosen folder:
#   curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash -s -- "<folder>"
# Safe to run again: it repairs an existing Bron vault and never overwrites your files.
set -euo pipefail

REPO="ziggoai/agent-bron"
DEFAULT_FOLDER="$HOME/Documents/Bron"
TTY="${BRON_TTY:-/dev/tty}"
TTY_STATE=0   # 0 not opened yet, 1 open on fd 3, 2 can't ask
ANSWER=""
STEP="starting"

say() { printf '%s\n' "$*"; }
fail() { printf '\nBron install stopped (%s): %s\n' "$STEP" "$*" >&2; exit 1; }
cant_ask() {
  fail "Bron needs an answer but can't ask in this window. Run it again with the folder to use, for example:
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | bash -s -- \"$DEFAULT_FOLDER\""
}

# ask "<question>" "<default>": sets ANSWER; returns 1 when nobody can be asked.
ask() {
  if [ "$TTY_STATE" = 0 ]; then
    if { exec 3<"$TTY"; } 2>/dev/null; then TTY_STATE=1; else TTY_STATE=2; fi
  fi
  [ "$TTY_STATE" = 1 ] || return 1
  printf '%s ' "$1"
  ANSWER=""
  IFS= read -r ANSWER <&3 || true
  [ -n "$ANSWER" ] || ANSWER="$2"
  printf '\n'
  return 0
}

confirm() {
  [ "${BRON_YES:-}" = "1" ] && return 0
  ask "$1 [y/N]" "n" || cant_ask
  case "$ANSWER" in y|Y|yes|Yes|YES) return 0 ;; esac
  say "Nothing was changed."
  exit 1
}

expand() {  # expand a leading ~ and make the path absolute
  local p="$1"
  case "$p" in "~") p="$HOME" ;; "~/"*) p="$HOME/${p#\~/}" ;; esac
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  while [ "${#p}" -gt 1 ] && [ "${p%/}" != "$p" ]; do p="${p%/}"; done
  printf '%s' "$p"
}

CLOUD_DOCS="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
# iCloud Drive itself, or Desktop/Documents while "Desktop & Documents Folders" sync is on
# (macOS then keeps their copies in iCloud Drive's Desktop and Documents folders).
is_icloud() {
  case "$1" in
    "$HOME/Library/Mobile Documents"|"$HOME/Library/Mobile Documents/"*) return 0 ;;
    "$HOME/Documents"|"$HOME/Documents/"*) [ -d "$CLOUD_DOCS/Documents" ] && return 0 ;;
    "$HOME/Desktop"|"$HOME/Desktop/"*) [ -d "$CLOUD_DOCS/Desktop" ] && return 0 ;;
  esac
  return 1
}

warn_icloud() {
  say "$1 is synced with iCloud Drive. Bron's engine doesn't work well there (iCloud can move its files away)."
  say "To use a folder outside iCloud instead, answer n and run:
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | bash -s -- \"$HOME/Bron\""
  confirm "Install there anyway?"
}

is_system_folder() {
  case "$1" in
    /|"$HOME"|/Users|/Volumes|/System|/System/*|/Library|/Library/*|/Applications|/Applications/*|/usr|/usr/*|/bin|/bin/*|/sbin|/sbin/*|/etc|/etc/*|/private/etc|/private/etc/*|/opt|/opt/*|"$HOME/Library"|"$HOME/Library/"*) return 0 ;;
  esac
  return 1
}

# 1. This Mac
STEP="checking this Mac"
[ "$(uname -s)" = "Darwin" ] || fail "Bron installs on macOS only for now."
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 12 ] 2>/dev/null || fail "Bron needs macOS 12 or newer."
command -v curl >/dev/null 2>&1 || fail "the curl command is missing."
command -v tar >/dev/null 2>&1 || fail "the tar command is missing."
if ! command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
  say "Note: install Claude Code or Codex before talking to Bron."
fi

# 2. The folder
STEP="choosing the folder"
TARGET="$(expand "${1:-$PWD}")"
if is_icloud "$TARGET"; then
  warn_icloud "$TARGET"
elif is_system_folder "$TARGET"; then
  say "Bron shouldn't be installed straight into $TARGET."
  ask "Where should Bron live? Press Enter for ~/Documents/Bron, or type a folder:" "$DEFAULT_FOLDER" || cant_ask
  TARGET="$(expand "$ANSWER")"
  if is_system_folder "$TARGET" && ! is_icloud "$TARGET"; then fail "$TARGET can't be used either; choose a folder of your own."; fi
  if is_icloud "$TARGET"; then
    warn_icloud "$TARGET"
  fi
  case "$TARGET" in "$HOME"/*) say "Installing into ~/${TARGET#$HOME/}" ;; *) say "Installing into $TARGET" ;; esac
fi
if [ -f "$TARGET/System/Core/VERSION" ]; then
  say "Found a Bron vault in $TARGET; repairing it. Your files are kept."
elif [ -d "$TARGET" ]; then
  count="$(ls -A "$TARGET" 2>/dev/null | grep -vc '^\.DS_Store$' || true)"
  if [ "$count" != "0" ]; then
    say "$TARGET already has $count item(s). Bron adds its own folders next to them and never changes your files."
    confirm "Install Bron here?"
  fi
fi

# 3. Download
STEP="downloading Bron"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LABEL="github"
if [ -n "${BRON_INSTALL_SOURCE:-}" ]; then
  if [ -d "$BRON_INSTALL_SOURCE" ]; then
    SRC="$(cd "$BRON_INSTALL_SOURCE" && pwd)"
    LABEL="$SRC"
  else
    tar -xzf "$BRON_INSTALL_SOURCE" -C "$WORK" || fail "the release file couldn't be unpacked."
    SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  fi
else
  tags="$(curl -fsSL --max-time 30 "https://api.github.com/repos/$REPO/tags?per_page=100")" || fail "GitHub didn't answer; check your internet connection and try again."
  VERSION="$(printf '%s\n' "$tags" | grep -oE '"name": *"v[0-9]+\.[0-9]+\.[0-9]+"' | sed -E 's/.*"v([0-9.]+)"/\1/' | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1 || true)"
  [ -n "$VERSION" ] || fail "Bron hasn't published a release yet."
  say "Downloading Bron $VERSION…"
  curl -fsSL --max-time 600 "https://codeload.github.com/$REPO/tar.gz/refs/tags/v$VERSION" -o "$WORK/bron.tar.gz" || fail "the download didn't finish; nothing was changed."
  tar -xzf "$WORK/bron.tar.gz" -C "$WORK" || fail "the download was damaged; nothing was changed."
  SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [ "$(cat "$SRC/core/VERSION" 2>/dev/null)" = "$VERSION" ] || fail "the download doesn't match version $VERSION; nothing was changed."
fi
[ -f "$SRC/core/VERSION" ] || fail "that isn't a Bron release (no core/VERSION)."

# 4. uv
STEP="getting uv"
UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"; fi
if [ -z "$UV" ]; then
  say "Installing uv (the tool Bron uses to run its engine)…"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || fail "uv couldn't be installed; check your internet connection and try again."
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || fail "uv was installed but can't be found in ~/.local/bin."
fi

# 5–9. The vault
STEP="setting up the vault"
mkdir -p "$TARGET" || fail "the folder $TARGET couldn't be created."
VAULT="$(cd "$TARGET" && pwd)" || fail "the folder $TARGET couldn't be opened."
say "Setting up Bron's engine (this can take a minute the first time)…"
"$UV" venv --quiet --allow-existing --python 3.12 "$VAULT/.bron/venv" </dev/null 3<&- || fail "Python 3.12 couldn't be set up for Bron."
"$UV" pip install --quiet --python "$VAULT/.bron/venv/bin/python" --reinstall-package bron-engine "$SRC/core/Engine" </dev/null 3<&- || fail "Bron's engine couldn't be installed."
"$VAULT/.bron/venv/bin/python" -m bron.install "$VAULT" --tree "$SRC" --source "$LABEL" </dev/null 3<&- || fail "the vault couldn't be finished; run the same command again to repair it."

# 10. Done
say ""
say "Your Bron vault is ready at $VAULT."
say "Open this folder in Claude Code or Codex (desktop app or terminal), or in Obsidian, and say hi to Bron."
