#!/usr/bin/env bash
# Tests for validate-hook-wiring.sh. Plain bash, fixture-driven, zero deps beyond
# jq (which the script itself requires). Mirrors the block-em-dash.test.sh style:
# build a payload, run the script, assert on exit code and message.
#
# Run: bash config/scripts/validate-hook-wiring.test.sh
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/validate-hook-wiring.sh"
repo_root="$(cd "$here/../.." && pwd)"

pass=0
fail=0

# fixtures live in a scratch dir so tests never touch the real config/
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

hooks_dir="$work/hooks"
mkdir -p "$hooks_dir"
# Two real-looking hooks plus a .test.sh that must be ignored by the validator.
: >"$hooks_dir/foo.sh"
: >"$hooks_dir/bar.sh"
: >"$hooks_dir/foo.test.sh"

# write_settings <file> <json>
write_settings() { printf '%s\n' "$2" >"$1"; }

both_wired='{
  "hooks": { "PreToolUse": [
    { "matcher": "Write|Edit", "hooks": [ { "type": "command", "command": "/x/foo.sh" } ] },
    { "matcher": "Write|Edit|Bash", "hooks": [ { "type": "command", "command": "/x/bar.sh" } ] }
  ] }
}'

missing_bar='{
  "hooks": { "PreToolUse": [
    { "matcher": "Write|Edit", "hooks": [ { "type": "command", "command": "/x/foo.sh" } ] }
  ] }
}'

empty_matcher='{
  "hooks": { "PreToolUse": [
    { "matcher": "Write|Edit", "hooks": [ { "type": "command", "command": "/x/foo.sh" } ] },
    { "matcher": "", "hooks": [ { "type": "command", "command": "/x/bar.sh" } ] }
  ] }
}'

extra_unrelated='{
  "hooks": { "PreToolUse": [
    { "matcher": "Write|Edit", "hooks": [ { "type": "command", "command": "/x/foo.sh" } ] },
    { "matcher": "Write|Edit|Bash", "hooks": [ { "type": "command", "command": "/x/bar.sh" } ] },
    { "matcher": "Read", "hooks": [ { "type": "command", "command": "/x/other.sh" } ] }
  ] }
}'

no_hooks_key='{ "model": "whatever" }'

# check <name> <expected_exit> <settings_json> [expected_substring]
check() {
  local name="$1" want_exit="$2" json="$3" want_sub="${4:-}"
  local sfile="$work/settings.json"
  write_settings "$sfile" "$json"
  local out ; out="$(bash "$script" "$sfile" "$hooks_dir" 2>&1)"
  local got=$?
  local ok=1
  [ "$got" -eq "$want_exit" ] || ok=0
  if [ -n "$want_sub" ] && ! printf '%s' "$out" | grep -qF "$want_sub"; then ok=0; fi
  if [ "$ok" -eq 1 ]; then
    pass=$((pass+1)); printf 'ok   %s\n' "$name"
  else
    fail=$((fail+1))
    printf 'FAIL %s (exit want=%s got=%s)\n' "$name" "$want_exit" "$got"
    printf '     output: %s\n' "$out"
  fi
}

check "all hooks wired -> pass"                0 "$both_wired"
check "unwired hook -> fail, names it"         1 "$missing_bar"     "bar.sh"
check "wired but empty matcher -> fail"        1 "$empty_matcher"   "bar.sh"
check "extra unrelated hooks -> still pass"    0 "$extra_unrelated"
check "no hooks key at all -> fail"            1 "$no_hooks_key"    "foo.sh"

# missing settings file -> nonzero with a clear error
out="$(bash "$script" "$work/does-not-exist.json" "$hooks_dir" 2>&1)"; got=$?
if [ "$got" -ne 0 ] && printf '%s' "$out" | grep -qiF "not found"; then
  pass=$((pass+1)); printf 'ok   missing settings file -> error\n'
else
  fail=$((fail+1)); printf 'FAIL missing settings file (exit=%s): %s\n' "$got" "$out"
fi

# .test.sh fixtures must be ignored (foo.test.sh not required to be wired)
check ".test.sh files are ignored"             0 "$both_wired"

# integration: the repo's real config/settings.json must wire the real hooks
if [ -f "$repo_root/config/settings.json" ]; then
  out="$(bash "$script" "$repo_root/config/settings.json" "$repo_root/config/hooks" 2>&1)"; got=$?
  if [ "$got" -eq 0 ]; then
    pass=$((pass+1)); printf 'ok   real config/settings.json wires real hooks\n'
  else
    fail=$((fail+1)); printf 'FAIL real config/settings.json (exit=%s): %s\n' "$got" "$out"
  fi
else
  printf 'skip real config/settings.json (file not present yet)\n'
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
