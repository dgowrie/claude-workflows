#!/usr/bin/env bash
# PreToolUse hook: block the em dash (U+2014), en dash (U+2013), and horizontal
# bar (U+2015) in any content Claude authors via Write/Edit/Bash. Enforces the
# global CLAUDE.md rule "No em dashes anywhere, ever" - including inline Bash
# (e.g. `gh`/`git` bodies), the gap that let one slip through before. Exit 2 =
# block the tool call and feed stderr back to Claude.
set -euo pipefail

# Hard dependency: without jq we cannot read the tool input. Under `set -e` a
# missing jq would abort with a generic "command not found" and an ambiguous
# exit code; block explicitly with an actionable reason instead.
if ! command -v jq >/dev/null 2>&1; then
  echo "Blocked: block-em-dash hook requires 'jq', which was not found on PATH. Install jq, then retry." >&2
  exit 2
fi

input=$(cat)

# Pull the author-supplied text out of whichever tool fired:
#   Write     -> .tool_input.content
#   Edit      -> .tool_input.new_string
#   Bash      -> .tool_input.command
#   MultiEdit -> .tool_input.edits[].new_string
# (NotebookEdit uses .tool_input.new_source if this matcher is ever widened.)
# Only author-supplied *new* text is scanned; Edit's old_string is deliberately
# excluded so a dash can still be removed. A malformed-JSON parse failure fails
# closed (exit 2), consistent with the missing-jq guard above.
if ! content=$(printf '%s' "$input" | jq -r '
  [ .tool_input.content, .tool_input.new_string, .tool_input.new_source, .tool_input.command, (.tool_input.edits[]?.new_string) ]
  | map(select(. != null))
  | join("\n")
'); then
  echo "Blocked: block-em-dash hook could not parse the tool input as JSON. This is unexpected; retry, and report it if it persists." >&2
  exit 2
fi

# Match the UTF-8 byte sequences for U+2013 EN DASH (e2 80 93), U+2014 EM DASH
# (e2 80 94), and U+2015 HORIZONTAL BAR (e2 80 95) - the same misuse class the
# rule guards against. Matching bytes under LC_ALL=C is locale-independent (a C
# locale would otherwise match the pattern's individual bytes and false-positive
# on other non-ASCII content) and keeps this script free of the characters it
# forbids, so it no longer self-blocks Write/Edit.
if printf '%s' "$content" | LC_ALL=C grep -q $'\xe2\x80[\x93\x94\x95]'; then
  echo "Blocked: em/en dash (U+2014, U+2013, U+2015) forbidden anywhere (global CLAUDE.md: \"No em dashes anywhere, ever\"). Replace with a hyphen, comma, semicolon, or parentheses, then retry." >&2
  exit 2
fi

exit 0
