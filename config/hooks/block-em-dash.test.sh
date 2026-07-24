#!/usr/bin/env bash
# Regression tests for block-em-dash.sh. Feeds JSON PreToolUse payloads to the
# hook and asserts the exit code (2 = block, 0 = pass). Run: bash <this file>.
#
# Dash bytes are generated via printf escapes so this test never embeds the
# forbidden characters in its own source (which would self-block editing it).
set -uo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/block-em-dash.sh"
EM=$(printf '\xe2\x80\x94')   # U+2014 EM DASH
EN=$(printf '\xe2\x80\x93')   # U+2013 EN DASH
BAR=$(printf '\xe2\x80\x95')  # U+2015 HORIZONTAL BAR
pass=0; fail=0

check() { # name expected_exit json
  local name=$1 want=$2 json=$3 got err
  # Capture stderr (discard stdout) so an unexpected hook error is visible on
  # failure instead of looking like a legitimate block/pass exit code.
  err=$(printf '%s' "$json" | "$HOOK" 2>&1 >/dev/null)
  got=$?
  if [ "$got" -eq "$want" ]; then
    printf 'PASS  %-52s (exit %s)\n' "$name" "$got"; pass=$((pass+1))
  else
    printf 'FAIL  %-52s (want %s got %s)\n' "$name" "$want" "$got"; fail=$((fail+1))
    [ -n "$err" ] && printf '      stderr: %s\n' "$err"
  fi
}

# Build a {tool_name, tool_input:{<field>:<value>}} payload without embedding
# raw values in the shell (jq --arg is literal, no interpretation).
j() { jq -n --arg t "$1" --arg k "$2" --arg v "$3" '{tool_name:$t, tool_input:{($k):$v}}'; }

# Bash: the coverage this hook change adds.
check "Bash + em dash blocks"           2 "$(j Bash command "gh pr comment -b 'a${EM}b'")"
check "Bash + en dash blocks"           2 "$(j Bash command "echo a${EN}b")"
check "Bash + horizontal bar blocks"    2 "$(j Bash command "echo a${BAR}b")"
check "Bash clean passes"               0 "$(j Bash command "git status && ls -la")"

# Write/Edit: pre-existing coverage must keep working.
check "Write + em dash blocks"          2 "$(j Write content "title ${EM} sub")"
check "Write clean passes"              0 "$(j Write content "clean hyphen - text")"
check "Edit + em dash blocks"           2 "$(j Edit new_string "a ${EM} b")"
check "Edit clean passes"               0 "$(j Edit new_string "a - b")"

# False-positive guards: the locale hazard fixed in PR #44 must stay fixed.
check "Bash + accented char passes"     0 "$(j Bash command "echo café résumé")"
check "Bash + emoji passes"             0 "$(j Bash command "echo done 🎉")"
check "Bash + smart quotes passes"      0 "$(printf '{"tool_name":"Bash","tool_input":{"command":"echo “hi”"}}')"

# Workaround: a codepoint-escaped dash reference is literal ASCII, must pass.
check "Bash grep via \\x escape passes" 0 "$(j Bash command 'grep -rn $'"'"'\xe2\x80\x94'"'"' .')"

# Boundary cases.
check "Bash empty command passes"       0 "$(j Bash command "")"
check "Unrelated tool passes"           0 '{"tool_name":"Read","tool_input":{"file_path":"/x"}}'

echo "-----"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
