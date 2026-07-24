#!/usr/bin/env bash
# Assert every committed hook script has a live matcher wiring in a settings.json.
#
# Motivation (claude-workflows #24): committed hook *scripts* in config/hooks/ are
# inert unless ~/.claude/settings.json wires each one under PreToolUse with a
# matcher. That wiring used to be untracked, so a committed hook could silently
# never fire. This checker fails if any hook is unwired or wired with an empty
# matcher, so the tracked config/settings.json can't drift away from the hooks.
#
# It deliberately checks presence + a non-empty matcher only, NOT whether the
# matcher covers the "right" tools: inferring intended tools from a script is
# brittle, and tracking settings.json (the sibling change) already makes matcher
# edits visible in review.
#
# Usage: validate-hook-wiring.sh [SETTINGS_JSON] [HOOKS_DIR]
#   SETTINGS_JSON  defaults to <repo>/config/settings.json
#   HOOKS_DIR      defaults to <repo>/config/hooks
# Exit 0 = all hooks wired; 1 = a wiring problem; 2 = usage/dependency error.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_dir="$(cd "$here/.." && pwd)"

settings="${1:-$config_dir/settings.json}"
hooks_dir="${2:-$config_dir/hooks}"

if ! command -v jq >/dev/null 2>&1; then
  echo "error: validate-hook-wiring requires 'jq' on PATH." >&2
  exit 2
fi

if [ ! -f "$settings" ]; then
  echo "error: settings file not found: $settings" >&2
  exit 2
fi

if [ ! -d "$hooks_dir" ]; then
  echo "error: hooks dir not found: $hooks_dir" >&2
  exit 2
fi

# Map of wired-hook-basename -> non-empty? We collect every PreToolUse command
# and remember, per basename, whether ANY wiring for it has a non-empty matcher.
# Format per line: "<basename>\t<matcher>" (matcher may be empty).
wired="$(jq -r '
  (.hooks.PreToolUse // [])[]
  | (.matcher // "") as $m
  | (.hooks // [])[]
  | select(.type == "command")
  | "\(.command)\t\($m)"
' "$settings")"

problems=0

# Iterate committed hook scripts, skipping test files.
shopt -s nullglob
for path in "$hooks_dir"/*.sh; do
  base="$(basename "$path")"
  case "$base" in
    *.test.sh) continue ;;
  esac

  # Does any wired command share this basename, and does at least one such
  # wiring carry a non-empty matcher?
  found=0
  has_matcher=0
  while IFS=$'\t' read -r cmd matcher; do
    [ -n "$cmd" ] || continue
    if [ "$(basename "$cmd")" = "$base" ]; then
      found=1
      [ -n "$matcher" ] && has_matcher=1
    fi
  done <<<"$wired"

  if [ "$found" -eq 0 ]; then
    echo "MISSING wiring: $base is committed but no PreToolUse hook references it in $settings" >&2
    problems=$((problems+1))
  elif [ "$has_matcher" -eq 0 ]; then
    echo "EMPTY matcher: $base is wired but every matcher is empty in $settings (it will never fire)" >&2
    problems=$((problems+1))
  else
    echo "ok: $base wired"
  fi
done
shopt -u nullglob

if [ "$problems" -ne 0 ]; then
  echo "validate-hook-wiring: $problems problem(s) found." >&2
  exit 1
fi

echo "validate-hook-wiring: all hooks wired."
exit 0
