#!/usr/bin/env bash
# Tests for install-settings.sh. Uses CLAUDE_CONFIG_DIR to redirect the target
# away from the real ~/.claude, so tests never touch live config.
#
# Run: bash config/scripts/install-settings.test.sh
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/install-settings.sh"
source_file="$(cd "$here/.." && pwd)/settings.json"

pass=0
fail=0
ok()   { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# fresh install links the tracked file
fake="$work/home1"
out="$(CLAUDE_CONFIG_DIR="$fake" bash "$script" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && [ -L "$fake/settings.json" ] \
   && [ "$(readlink "$fake/settings.json")" = "$source_file" ]; then
  ok "fresh install creates symlink to tracked settings"
else
  bad "fresh install (rc=$rc): $out"
fi

# re-running is idempotent (still linked, reports already linked)
out="$(CLAUDE_CONFIG_DIR="$fake" bash "$script" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qF "already linked"; then
  ok "second install is idempotent"
else
  bad "idempotent install (rc=$rc): $out"
fi

# --check on a good link passes
out="$(CLAUDE_CONFIG_DIR="$fake" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -qF "ok: $fake/settings.json"; then
  ok "--check passes on a valid link"
else
  bad "--check on valid link (rc=$rc): $out"
fi

# existing regular file is backed up, then replaced by the symlink
fake2="$work/home2"
mkdir -p "$fake2"
printf '{"model":"old"}\n' >"$fake2/settings.json"
out="$(CLAUDE_CONFIG_DIR="$fake2" bash "$script" 2>&1)"; rc=$?
backups=( "$fake2"/settings.json.backup.* )
if [ "$rc" -eq 0 ] && [ -L "$fake2/settings.json" ] && [ -f "${backups[0]}" ] \
   && grep -qF '"model":"old"' "${backups[0]}"; then
  ok "existing regular file is backed up before linking"
else
  bad "backup-on-link (rc=$rc): $out"
fi

# clobber detection: a regular file where a symlink is expected -> nonzero,
# and the message distinguishes "content matches" from "drift".
fake3="$work/home3"
mkdir -p "$fake3"
cp "$source_file" "$fake3/settings.json"   # identical content, but a regular file
out="$(CLAUDE_CONFIG_DIR="$fake3" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qiF "regular file"; then
  ok "--check flags a clobbered symlink (regular file, content matches)"
else
  bad "--check clobber-matches (rc=$rc): $out"
fi

fake4="$work/home4"
mkdir -p "$fake4"
printf '{"model":"drifted"}\n' >"$fake4/settings.json"
out="$(CLAUDE_CONFIG_DIR="$fake4" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qiF "DRIFT"; then
  ok "--check reports DRIFT when a regular file differs"
else
  bad "--check drift (rc=$rc): $out"
fi

# --check when nothing is installed -> nonzero, NOT INSTALLED
fake5="$work/home5"
out="$(CLAUDE_CONFIG_DIR="$fake5" bash "$script" --check 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -qiF "NOT INSTALLED"; then
  ok "--check reports NOT INSTALLED when absent"
else
  bad "--check not-installed (rc=$rc): $out"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
