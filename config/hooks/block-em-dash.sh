#!/usr/bin/env bash
# PreToolUse hook: block em-dash (—, U+2014) in any content Claude authors via
# Write/Edit. Enforces the global CLAUDE.md rule "No em dashes anywhere, ever".
# Exit 2 = block the tool call and feed stderr back to Claude.
set -euo pipefail

input=$(cat)

# Pull the author-supplied text out of whichever tool fired:
#   Write -> .tool_input.content
#   Edit  -> .tool_input.new_string
# (NotebookEdit uses .tool_input.new_source if this matcher is ever widened.)
content=$(printf '%s' "$input" | jq -r '
  [ .tool_input.content, .tool_input.new_string, .tool_input.new_source ]
  | map(select(. != null))
  | join("\n")
')

# U+2014 EM DASH. Also catch the rarer U+2015 HORIZONTAL BAR and U+2013 EN DASH,
# which are the same misuse class the rule is guarding against.
if printf '%s' "$content" | grep -q '[—―–]'; then
  echo "Blocked: em-dash/en-dash forbidden anywhere (global CLAUDE.md: \"No em dashes anywhere, ever\"). Replace —/–/― with a hyphen, comma, semicolon, or parentheses, then retry." >&2
  exit 2
fi

exit 0
