#!/usr/bin/env bash
# Provision the tracked Claude Code settings template into ~/.claude, and check
# that the live settings still wire every committed hook.
#
# claude-workflows #24: personal posture keys (model, theme, sandbox, skip*
# prompts) must NOT be committed to this public repo, and at user-global scope
# there is a single settings.json with no private overlay (verified: a user-level
# settings.local.json is not honored for these keys). So instead of tracking or
# symlinking the live file, we track a template, config/settings.example.json,
# holding only shareable keys (hook wiring + attribution policy). You copy it once
# to the untracked ~/.claude/settings.json (--init) and add your private posture
# keys there. --check then asserts the live file still wires every committed hook.
#
# Usage:
#   install-settings.sh            (--check) verify live settings wire all hooks
#   install-settings.sh --check    same as no args
#   install-settings.sh --init     copy the template to ~/.claude/settings.json
#                                   (only if it does not already exist)
#
# Override the target dir for testing:  CLAUDE_CONFIG_DIR=/tmp/fake ./install-settings.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_dir="$(cd "$here/.." && pwd)"

source_file="$config_dir/settings.example.json"
target_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
target_file="$target_dir/settings.json"

mode="check"
case "${1:-}" in
  ""|--check) mode="check" ;;
  --init)     mode="init" ;;
  *) echo "usage: install-settings.sh [--check|--init]" >&2; exit 2 ;;
esac

if ! command -v jq >/dev/null 2>&1; then
  echo "error: install-settings requires 'jq' on PATH." >&2
  exit 2
fi

if [ ! -f "$source_file" ]; then
  echo "error: tracked settings template not found: $source_file" >&2
  exit 2
fi

run_validation() {
  bash "$here/validate-hook-wiring.sh" "$1" "$config_dir/hooks"
}

if [ "$mode" = "init" ]; then
  # Never clobber an existing live file: it holds private posture keys.
  if [ -e "$target_file" ] || [ -L "$target_file" ]; then
    echo "exists: $target_file already present; refusing to overwrite." >&2
    echo "        Reconcile by hand, or run install-settings.sh --check to verify wiring." >&2
    exit 1
  fi
  mkdir -p "$target_dir"
  cp "$source_file" "$target_file"
  echo "created $target_file from $source_file"
  echo "next: add your private posture keys (model, theme, sandbox, skip*) to $target_file;"
  echo "      they are intentionally NOT tracked. See config/scripts/README.md."
  run_validation "$target_file"
  exit 0
fi

# mode = check: the live file must exist and wire every committed hook.
if [ ! -f "$target_file" ]; then
  echo "NOT INSTALLED: $target_file does not exist. Run install-settings.sh --init to create it." >&2
  exit 1
fi

if ! jq -e . "$target_file" >/dev/null 2>&1; then
  echo "error: live settings is not valid JSON: $target_file" >&2
  exit 2
fi

# Soft drift signal: the live hook wiring differs from the tracked template.
# Non-fatal (your matchers may legitimately differ), but surfaces silent changes
# so the template can be kept honest.
if ! jq -e -s '.[0].hooks == .[1].hooks' "$target_file" "$source_file" >/dev/null; then
  echo "note: live hooks differ from the tracked template ($source_file)." >&2
  echo "      If intentional, update the template so review reflects reality." >&2
fi

# Hard guarantee (#24): every committed hook is actually wired in the LIVE file.
run_validation "$target_file"
