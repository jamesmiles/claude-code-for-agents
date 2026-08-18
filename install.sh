#!/usr/bin/env bash
# Install claude-code-for-agents.
#
#   curl -fsSL https://raw.githubusercontent.com/jamesmiles/claude-code-for-agents/main/install.sh | bash
#
# or, from a clone:   ./install.sh [--copy]
#
# Environment:
#   CC4A_REF    branch or tag to install from   (default: main)
#   CC4A_DEST   install directory               (default: ~/.claude/tools)
set -euo pipefail

REPO="jamesmiles/claude-code-for-agents"
REF="${CC4A_REF:-main}"
TOOLS=(cc4a)
DEST="${CC4A_DEST:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/tools}"
RAW="https://raw.githubusercontent.com/$REPO/$REF"

MODE="copy"
[ "${1:-}" = "--copy" ] && MODE="copy"

# Are we running from a clone, or piped from curl?
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname -- "${BASH_SOURCE[0]}")/tools/${TOOLS[0]}" ]; then
  SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  [ "${1:-}" = "--copy" ] || MODE="link"
fi

die() { echo "install failed: $*" >&2; exit 1; }

fetch() { # fetch <url> <dest>
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --proto '=https' --tlsv1.2 -o "$2" "$1" || return 1
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1" || return 1
  else
    die "need curl or wget"
  fi
}

command -v python3 >/dev/null 2>&1 || die "cc4a needs python3 on PATH"

mkdir -p "$DEST" || die "cannot create $DEST"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "claude-code-for-agents -> $DEST"
for tool in "${TOOLS[@]}"; do
  target="$DEST/$tool"
  if [ -n "$SRC" ]; then
    staged="$SRC/tools/$tool"
  else
    staged="$tmp/$tool"
    fetch "$RAW/tools/$tool" "$staged" || die "could not download $tool from $RAW"
    # Guard against a truncated or error-page download becoming an executable.
    head -n1 "$staged" | grep -q '^#!' || die "$tool does not look like a script (bad ref '$REF'?)"
    grep -q 'claude-code-for-agents' "$staged" || die "$tool contents unexpected; refusing to install"
  fi

  [ -e "$target" ] || [ -L "$target" ] && rm -f "$target"
  if [ "$MODE" = "link" ]; then ln -s "$staged" "$target"; else cp "$staged" "$target"; fi
  chmod +x "$target"
  echo "  $MODE  $target"
done

cat <<MSG

Done. Try:  $DEST/cc4a --help

These are plain scripts — nothing is registered with Claude Code and no context is
consumed until one is run. To let Claude reach for them on its own, add a line to
your CLAUDE.md; see the README section "Making an agent aware of a tool".
MSG
