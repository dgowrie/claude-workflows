#!/usr/bin/env bash
# Link the tracked config/settings.json into ~/.claude, and check for drift.
#
# claude-workflows #24: ~/.claude/settings.json holds the hook *wiring* that makes
# committed hooks fire, plus model/theme/sandbox prefs. It was an untracked
# regular file, so its state could drift from the repo silently. This script
# makes it a symlink to the tracked config/settings.json (source of truth) and,
# in --check mode, reports drift.
#
# KNOWN CAVEAT (unverified): Claude Code's own settings writer (e.g. `/config`,
# changing the theme in the TUI) may REPLACE settings.json rather than write
# through the symlink, silently turning it back into a regular file. --check
# detects that case ("regular file where a symlink is expected") so it can be
# re-linked; the pre-existing file is preserved as a .backup so no edits are lost.
#
# Usage:
#   install-settings.sh          link settings.json (backs up any existing file)
#   install-settings.sh --check  report link status + drift; nonzero if drifted
#
# Override the target dir for testing:  CLAUDE_CONFIG_DIR=/tmp/fake ./install-settings.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_dir="$(cd "$here/.." && pwd)"

source_file="$config_dir/settings.json"
target_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
target_file="$target_dir/settings.json"

mode="link"
if [ "${1:-}" = "--check" ]; then
  mode="check"
elif [ -n "${1:-}" ]; then
  echo "usage: install-settings.sh [--check]" >&2
  exit 2
fi

if [ ! -f "$source_file" ]; then
  echo "error: tracked settings not found: $source_file" >&2
  exit 2
fi

# resolve_link <path> -> prints the symlink target (absolute) or empty if not a link
resolve_link() {
  if [ -L "$1" ]; then
    local dest ; dest="$(readlink "$1")"
    case "$dest" in
      /*) printf '%s' "$dest" ;;
      *)  printf '%s' "$(cd "$(dirname "$1")" && cd "$(dirname "$dest")" && pwd)/$(basename "$dest")" ;;
    esac
  fi
}

run_validation() {
  bash "$here/validate-hook-wiring.sh" "$source_file" "$config_dir/hooks"
}

if [ "$mode" = "check" ]; then
  status=0
  if [ -L "$target_file" ]; then
    dest="$(resolve_link "$target_file")"
    if [ "$dest" = "$source_file" ]; then
      echo "ok: $target_file -> $source_file"
    else
      echo "WARN: $target_file is a symlink to '$dest', not the tracked $source_file" >&2
      status=1
    fi
  elif [ -f "$target_file" ]; then
    if cmp -s "$target_file" "$source_file"; then
      echo "WARN: $target_file is a regular file (not a symlink) but its content matches the tracked file." >&2
      echo "      A Claude Code settings write may have replaced the symlink. Re-run install-settings.sh to re-link." >&2
    else
      echo "DRIFT: $target_file is a regular file and differs from tracked $source_file." >&2
      echo "      Reconcile the differences into the tracked file, then re-run install-settings.sh." >&2
    fi
    status=1
  else
    echo "NOT INSTALLED: $target_file does not exist. Run install-settings.sh to link it." >&2
    status=1
  fi
  # Wiring must hold regardless of link status.
  run_validation
  exit "$status"
fi

# mode = link
if [ -L "$target_file" ] && [ "$(resolve_link "$target_file")" = "$source_file" ]; then
  echo "already linked: $target_file -> $source_file"
  run_validation
  exit 0
fi

mkdir -p "$target_dir"

if [ -e "$target_file" ] || [ -L "$target_file" ]; then
  backup="$target_file.backup.$(date +%Y%m%d%H%M%S)"
  mv "$target_file" "$backup"
  echo "backed up existing settings to $backup"
fi

ln -s "$source_file" "$target_file"
echo "linked $target_file -> $source_file"
run_validation
