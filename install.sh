#!/usr/bin/env bash
# Install claude-code-for-agents.
#
#   curl -fsSL https://raw.githubusercontent.com/jamesmiles/claude-code-for-agents/main/install.sh | bash
#
# or, from a clone:   ./install.sh [--copy] [--force]
#
# Environment:
#   CC4A_REF    branch or tag to install from   (default: main)
#   CC4A_DEST   install directory               (default: ~/.claude/tools)
#   CC4A_BIN    directory to link onto PATH     (default: first writable dir on PATH)
set -euo pipefail

REPO="jamesmiles/claude-code-for-agents"
REF="${CC4A_REF:-main}"
TOOLS=(cc4a)
DEST="${CC4A_DEST:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/tools}"
RAW="https://raw.githubusercontent.com/$REPO/$REF"

MODE="copy"; FORCE=0
for a in "$@"; do
  case "$a" in
    --copy) MODE="copy" ;;
    --force) FORCE=1 ;;
  esac
done

# Are we running from a clone, or piped from curl?
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname -- "${BASH_SOURCE[0]}")/tools/${TOOLS[0]}" ]; then
  SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  case " $* " in *" --copy "*) ;; *) MODE="link" ;; esac
fi

die() { echo "install failed: $*" >&2; exit 1; }
on_path() { case ":${PATH:-}:" in *":$1:"*) return 0 ;; *) return 1 ;; esac; }

fetch() {
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
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

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

  # Never silently replace a symlink that points somewhere else — it is usually a
  # development clone, and overwriting it detaches edits from what actually runs.
  if [ -L "$target" ]; then
    current="$(readlink "$target")"
    if [ "$current" != "$staged" ] && [ "$FORCE" -eq 0 ]; then
      repo="$(cd -- "$(dirname -- "$current")/.." 2>/dev/null && pwd)" || repo=""
      echo >&2
      echo "refusing to replace a symlink:" >&2
      echo "  $target" >&2
      echo "  -> $current" >&2
      echo >&2
      echo "That is probably a clone you develop in; replacing it with a copy would" >&2
      echo "silently detach your edits from what actually runs." >&2
      echo >&2
      if [ -n "$repo" ] && [ -d "$repo/.git" ]; then
        echo "To update that clone:      git -C $repo pull" >&2
      fi
      echo "To replace it anyway:      re-run with --force" >&2
      exit 1
    fi
  fi

  rm -f "$target"
  if [ "$MODE" = "link" ]; then ln -s "$staged" "$target"; else cp "$staged" "$target"; fi
  chmod +x "$target"
  echo "  $MODE  $target"
done

# Put it on PATH, or say exactly how to.
linked=""
if ! on_path "$DEST"; then
  for bin in ${CC4A_BIN:-} "$HOME/.local/bin" "$HOME/bin" /usr/local/bin; do
    [ -n "$bin" ] || continue
    if [ -d "$bin" ] && [ -w "$bin" ] && on_path "$bin"; then
      for tool in "${TOOLS[@]}"; do
        ln -sf "$DEST/$tool" "$bin/$tool"
        echo "  link  $bin/$tool"
      done
      linked="$bin"
      break
    fi
  done
fi

echo
if on_path "$DEST" || [ -n "$linked" ]; then
  echo "Done. Try:  cc4a --help"
else
  echo "Done. Try:  $DEST/cc4a --help"
  echo
  echo "$DEST is not on your PATH. To type \`cc4a\` instead of the full path, add:"
  echo "  export PATH=\"$DEST:\$PATH\""
  echo "to your ~/.zshrc (or ~/.bashrc), then open a new shell."
fi

cat <<MSG

These are plain scripts — nothing is registered with Claude Code and no context is
consumed until one is run. To let Claude reach for them on its own, add a line to
your CLAUDE.md; see the README section "Making an agent aware of a tool".
MSG
