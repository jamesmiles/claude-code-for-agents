#!/usr/bin/env bash
# Install claude-code-for-agents scripts into ~/.claude/tools
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/tools"
MODE="link"
[ "${1:-}" = "--copy" ] && MODE="copy"

mkdir -p "$DEST"
echo "Installing to $DEST"
for tool in "$SRC"/tools/*; do
  [ -e "$tool" ] || continue
  chmod +x "$tool"
  target="$DEST/$(basename "$tool")"
  [ -e "$target" ] || [ -L "$target" ] && rm -f "$target"
  if [ "$MODE" = "link" ]; then ln -s "$tool" "$target"; else cp "$tool" "$target"; fi
  echo "  $MODE  $target"
done

cat <<MSG

Done. Try:  $DEST/cc-budget

These are plain scripts — nothing is registered with Claude Code and no context is
consumed until one is run. To let Claude reach for cc-budget on its own, add a line
to your CLAUDE.md; see the README section "Making an agent aware of a tool".
MSG
