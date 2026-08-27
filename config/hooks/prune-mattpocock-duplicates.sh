#!/usr/bin/env bash
#
# Prune Matt Pocock plugin skills that duplicate my own customized personal
# skills, so Claude only ever sees my versions.
#
# Why this exists:
#   The mattpocock-skills Claude Code plugin ships ~25 skills as one bundle
#   (installed for the `teach` skill, kept current via the plugin's auto-update).
#   Several bundle skills share a name with my personal ~/.claude/skills copies.
#   Slash invocation already favors mine (the plugin's are namespaced
#   /mattpocock-skills:<name>), but for the ones that auto-fire, the plugin's
#   description also loads and competes with mine on model-invocation.
#
#   skillOverrides cannot silence a plugin skill (verified: a namespaced key is
#   ignored, a bare key disables MY copy instead). Deleting the plugin's skill
#   folder from the cache does work and survives a session, but a plugin update
#   re-checkouts a fresh copy into a new version directory, bringing the
#   duplicates back. This SessionStart hook re-prunes them every session, so the
#   removal is durable and self-healing after updates.
#
# Scope: only the duplicates that auto-fire (and thus actually compete). The
# other name collisions in the bundle are disable-model-invocation, so they
# never auto-fire and cost nothing; they are left in place.
#
# Source of truth: claude-workflows/config/hooks/. Reached via a symlink in
# ~/.claude/hooks/. If Matt renames or moves one of these skills upstream, its
# plugin copy will reappear (name no longer matches); update the list below.

set -uo pipefail

plugin_root="${HOME}/.claude/plugins/cache/claude-plugins-official/mattpocock-skills"
[ -d "$plugin_root" ] || exit 0

# Personal skills the plugin also ships that auto-fire (no disable-model-invocation).
duplicates=(
  codebase-design
  domain-modeling
  grilling
  prototype
  tdd
  writing-for-agents
)

for name in "${duplicates[@]}"; do
  while IFS= read -r skill_md; do
    rm -rf "$(dirname "$skill_md")"
  done < <(find "$plugin_root" -type f -path "*/skills/*/${name}/SKILL.md" 2>/dev/null)
done

exit 0
