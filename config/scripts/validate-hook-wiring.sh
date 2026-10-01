#!/usr/bin/env bash
# Assert every committed hook script has a live wiring in a settings.json.
#
# Motivation (claude-workflows #24): committed hook *scripts* in config/hooks/ are
# inert unless a settings.json wires each one under some hook event. That wiring
# is easy to get wrong or let drift, so a committed hook could silently never
# fire. This checker fails if any hook is unwired. Run it against the tracked
# config/settings.example.json (does the template wire everything?) and against
# the live ~/.claude/settings.json (is your real config still wiring every
# committed hook?).
#
# It scans every hook event, not just PreToolUse, so lifecycle hooks (SessionStart,
# Stop, ...) count as wired on presence alone. A non-empty matcher is required only
# for the tool-matching events (PreToolUse / PostToolUse), where an empty matcher
# selects no tool and the hook never fires; lifecycle events take no matcher. It
# checks presence, NOT whether the matcher covers the "right" tools: inferring
# intended tools from a script is brittle, and the tracked example makes the
# intended matchers visible in review.
#
# A hook may opt out with a `# wiring: personal` comment marker: a machine-local
# hook that intentionally lives only in a private settings.json, never the tracked
# template. Such hooks are skipped by this check.
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

# Every wired command across all hook events, one "<command>\t<event>\t<matcher>"
# per line. Scanning every event (not just PreToolUse) lets lifecycle hooks count
# as wired; the matcher only gates the tool events (see is_matcher_required_event).
# Skip null/empty commands so a malformed entry can't surface as the string "null".
# Type guards (`?` and explicit type checks) keep valid-but-oddly-typed JSON
# (e.g. "hooks": [] or "PreToolUse": {}) from crashing jq under `set -e`; such
# structures are simply treated as "no wiring found".
wired="$(jq -r '
  (.hooks? // {}) as $h
  | (if ($h | type) == "object" then $h else {} end)
  | to_entries[]
  | .key as $event
  | (.value // []) as $groups
  | (if ($groups | type) == "array" then $groups else [] end)[]
  | (.matcher? // "") as $m
  | (.hooks? // [])
  | (if type == "array" then . else [] end)[]
  | select((.type? // "") == "command")
  | select(.command != null and .command != "")
  | "\(.command)\t\($event)\t\($m)"
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

# Only the tool-matching events select tools with a matcher; a lifecycle event
# (SessionStart, SessionEnd, Stop, SubagentStop, ...) takes no matcher, so being
# referenced there is enough to count as wired.
is_matcher_required_event() {
  case "$1" in
    PreToolUse|PostToolUse) return 0 ;;
    *) return 1 ;;
  esac
}

problems=0

# Iterate committed hook scripts, skipping test files.
shopt -s nullglob
for path in "$hooks_dir"/*.sh; do
  base="$(basename "$path")"
  case "$base" in
    *.test.sh) continue ;;
  esac

  # A hook opts out of the shared-template check with a `# wiring: personal`
  # marker: it is machine-local and lives only in a private settings.json.
  if grep -qE '^#[[:space:]]*wiring:[[:space:]]*personal([[:space:]]|$)' "$path"; then
    echo "skip: $base (marked personal, not expected in the shared template)"
    continue
  fi

  # Is this hook referenced anywhere, and where it is a tool event, does at least
  # one such wiring carry a non-empty matcher? A reference under a lifecycle event
  # (matcherless) satisfies the check on its own.
  found=0
  has_valid_matcher=0
  found_matcherless=0
  while IFS=$'\t' read -r cmd event matcher; do
    [ -n "$cmd" ] || continue
    if references_hook "$cmd" "$base"; then
      found=1
      if is_matcher_required_event "$event"; then
        [ -n "$matcher" ] && has_valid_matcher=1
      else
        found_matcherless=1
      fi
    fi
  done <<<"$wired"

  if [ "$found" -eq 0 ]; then
    echo "MISSING wiring: $base is committed but no hook in any event references it in $settings" >&2
    problems=$((problems+1))
  elif [ "$has_valid_matcher" -eq 0 ] && [ "$found_matcherless" -eq 0 ]; then
    echo "EMPTY matcher: $base is wired but every tool-event matcher is empty in $settings (it will never fire)" >&2
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
