#!/usr/bin/env bash
# PreToolUse hook: block the "Generated with Claude Code" footer and
# Co-Authored-By: Claude trailers in anything Claude authors. Enforces the
# global CLAUDE.md rule: "No Co-Authored-By trailers. No 'Generated with
# Claude Code' attribution. Anywhere." A base-harness instruction pushes this
# attribution into commits/PRs; the attribution:"" settings suppress the
# instruction, and this hook is the mechanical backstop if it slips through.
# Covers Write/Edit content (e.g. a PR body written to a temp file) and Bash
# command strings (inline `git commit -m` / `gh pr ... --body`).
# Exit 2 = block the tool call and feed stderr back to Claude.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "Blocked: block-claude-attribution hook requires 'jq', which was not found on PATH. Install jq, then retry." >&2
  exit 2
fi

input=$(cat)

# Pull author-supplied text out of whichever tool fired:
#   Write -> .tool_input.content
#   Edit  -> .tool_input.new_string
#   Bash  -> .tool_input.command  (inline commit/PR bodies)
content=$(printf '%s' "$input" | jq -r '
  [ .tool_input.content, .tool_input.new_string, .tool_input.new_source, .tool_input.command ]
  | map(select(. != null))
  | join("\n")
')

# Two precise patterns, chosen to avoid false-positiving on prose that merely
# discusses the rule:
#   1. The Co-Authored-By trailer naming Claude (a bare "Co-Authored-By" in
#      prose has no ": Claude" after it).
#   2. The generated-with footer in its real markdown-link form (prose like
#      No "Generated with Claude Code" has no [ ] brackets).
if printf '%s' "$content" | grep -qiE 'Co-Authored-By:[[:space:]]*Claude'; then
  echo "Blocked: 'Co-Authored-By: Claude' trailer forbidden anywhere (global CLAUDE.md). Remove the trailer, then retry." >&2
  exit 2
fi

if printf '%s' "$content" | grep -qE 'Generated with \[Claude Code\]'; then
  echo "Blocked: 'Generated with [Claude Code]' attribution forbidden anywhere (global CLAUDE.md). Remove the attribution footer, then retry." >&2
  exit 2
fi

exit 0
