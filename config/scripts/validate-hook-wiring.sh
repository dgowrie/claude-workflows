#!/usr/bin/env bash
# Assert every committed hook script has a live matcher wiring in a settings.json.
#
# Motivation (claude-workflows #24): committed hook *scripts* in config/hooks/ are
# inert unless a settings.json wires each one under PreToolUse with a matcher.
# That wiring is easy to get wrong or let drift, so a committed hook could
# silently never fire. This checker fails if any hook is unwired or wired with an
# empty matcher. Run it against the tracked config/settings.example.json (does the
# template wire everything?) and against the live ~/.claude/settings.json (is your
# real config still wiring every committed hook?).
#
# It deliberately checks presence + a non-empty matcher only, NOT whether the
# matcher covers the "right" tools: inferring intended tools from a script is
# brittle, and the tracked example makes the intended matchers visible in review.
#
# Usage: validate-hook-wiring.sh [SETTINGS_JSON] [HOOKS_DIR]
#   SETTINGS_JSON  defaults to <repo>/config/settings.example.json
#   HOOKS_DIR      defaults to <repo>/config/hooks
# Exit 0 = all hooks wired; 1 = a wiring problem; 2 = usage/dependency error.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_dir="$(cd "$here/.." && pwd)"

settings="${1:-$config_dir/settings.example.json}"
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

# Fail with a clear, script-level message if settings is not valid JSON, rather
# than letting `set -e` abort on jq's raw parse error further down.
if ! jq -e . "$settings" >/dev/null 2>&1; then
  echo "error: settings file is not valid JSON: $settings" >&2
  exit 2
fi

# Every PreToolUse command with its matcher, one "<command>\t<matcher>" per line.
# Skip null/empty commands so a malformed entry can't surface as the string "null".
wired="$(jq -r '
  (.hooks.PreToolUse // [])[]
  | (.matcher // "") as $m
  | (.hooks // [])[]
  | select(.type == "command")
  | select(.command != null and .command != "")
  | "\(.command)\t\($m)"
' "$settings")"

# Does a wired command string reference hook script $base? Match the basename as a
# path/word token so a command carrying args ("/x/foo.sh --flag") or a shell
# prefix ("sh -c '/x/foo.sh'", "bash /x/foo.sh") still counts as wired, without
# foo.sh spuriously matching inside foobar.sh.
references_hook() {
  local cmd="$1" base="$2" esc re
  esc="${base//./\\.}"
  re="(^|[/[:space:]'\"])${esc}([[:space:]'\"]|\$)"
  [[ "$cmd" =~ $re ]]
}

problems=0

# Iterate committed hook scripts, skipping test files.
shopt -s nullglob
for path in "$hooks_dir"/*.sh; do
  base="$(basename "$path")"
  case "$base" in
    *.test.sh) continue ;;
  esac

  # Does any wired command reference this hook, and does at least one such wiring
  # carry a non-empty matcher?
  found=0
  has_matcher=0
  while IFS=$'\t' read -r cmd matcher; do
    [ -n "$cmd" ] || continue
    if references_hook "$cmd" "$base"; then
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
