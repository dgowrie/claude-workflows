#!/usr/bin/env bash
# Tests for install-settings.sh. Uses CLAUDE_CONFIG_DIR to redirect the target
# away from the real ~/.claude, so tests never touch live config.
#
# Run: bash config/scripts/install-settings.test.sh
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/install-settings.sh"
example="$(cd "$here/.." && pwd)/settings.example.json"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }

# mktemp -d works without a template on GNU and modern macOS/BSD; the -t fallback
# keeps older BSD mktemp happy too.
work="$(mktemp -d 2>/dev/null || mktemp -d -t cc-install-test)"
trap 'rm -rf "$work"' EXIT

# --init into an empty target dir copies the template verbatim (regular file)
fake="$work/home1"
out="$(CLAUDE_CONFIG_DIR="$fake" bash "$script" --init 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && [ -f "$fake/settings.json" ] && [ ! -L "$fake/settings.json" ] \
   && cmp -s "$fake/settings.json" "$example"; then
  ok "--init copies the template to an absent target"
else
  bad "--init fresh (rc=$rc): $out"
fi

# --init refuses to overwrite an existing target (private posture must survive)
printf '{"model":"private","hooks":{}}\n' >"$fake/settings.json"
before="$(cat "$fake/settings.json")"
out="$(CLAUDE_CONFIG_DIR="$fake" bash "$script" --init 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qiF "already present" \
   && [ "$(cat "$fake/settings.json")" = "$before" ]; then
  ok "--init refuses to overwrite an existing target"
else
  bad "--init no-clobber (rc=$rc): $out"
fi

# --check when nothing is installed -> nonzero, NOT INSTALLED
fake2="$work/home2"
out="$(CLAUDE_CONFIG_DIR="$fake2" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qiF "NOT INSTALLED"; then
  ok "--check reports NOT INSTALLED when absent"
else
  bad "--check not-installed (rc=$rc): $out"
fi

# default (no args) behaves like --check
out="$(CLAUDE_CONFIG_DIR="$fake2" bash "$script" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qiF "NOT INSTALLED"; then
  ok "no args defaults to --check"
else
  bad "default is check (rc=$rc): $out"
fi

# --check passes when the live file wires every committed hook (template + posture)
fake3="$work/home3"
mkdir -p "$fake3"
jq '. + {model: "private", theme: "dark"}' "$example" >"$fake3/settings.json"
out="$(CLAUDE_CONFIG_DIR="$fake3" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qiF "all hooks wired"; then
  ok "--check passes when live wires all committed hooks"
else
  bad "--check valid (rc=$rc): $out"
fi

# --check soft-notes when live hooks differ from the template, but still passes
# if the wiring is valid (all hooks present, non-empty matcher)
fake4="$work/home4"
mkdir -p "$fake4"
jq '.hooks.PreToolUse[0].matcher = "Write"' "$example" >"$fake4/settings.json"
out="$(CLAUDE_CONFIG_DIR="$fake4" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qiF "differ from the tracked template"; then
  ok "--check soft-notes hook drift but passes on valid wiring"
else
  bad "--check soft drift (rc=$rc): $out"
fi

# --check fails when the live file is missing a committed hook's wiring
fake5="$work/home5"
mkdir -p "$fake5"
jq 'del(.hooks.PreToolUse[1])' "$example" >"$fake5/settings.json"
out="$(CLAUDE_CONFIG_DIR="$fake5" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -qiF "MISSING wiring"; then
  ok "--check fails when a committed hook is unwired in live"
else
  bad "--check missing wiring (rc=$rc): $out"
fi

# --check errors clearly on invalid JSON in the live file
fake6="$work/home6"
mkdir -p "$fake6"
printf '{not json\n' >"$fake6/settings.json"
out="$(CLAUDE_CONFIG_DIR="$fake6" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -qiF "not valid JSON"; then
  ok "--check errors on invalid live JSON"
else
  bad "--check invalid json (rc=$rc): $out"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
