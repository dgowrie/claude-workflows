#!/bin/bash
# ~/.claude/sync-skills.sh
# Three-tier skill sync:
#   Source of truth: ~/dev/claude-workflows/skills/ (version-controlled repo)
#   Deployment:      ~/.claude/skills/ (symlinks to repo)
#   Cowork bridge:   $COWORK_SKILLS (symlinks to ~/.claude/skills/)
#
# Handles:
#   - Cowork-created skills: migrate to repo, symlink both tiers
#   - Repo-only skills: symlink to ~/.claude/skills/ and Cowork
#   - ~/.claude/skills/ real dirs (manual creates): migrate to repo, replace with symlink
#   - Broken symlinks: clean up in both locations

REPO="$HOME/dev/claude-workflows/skills"
CANONICAL="$HOME/.claude/skills"
COWORK="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/827f9b90-1736-4f25-b0d0-9f7f9006212c/0f5b018c-ecbb-4c63-add7-ae92ef923db7/skills"
LOG="$HOME/.claude/sync-skills.log"

# Cowork built-in skills - never migrate these
COWORK_BUILTINS="docx pdf pptx schedule skill-creator xlsx"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

is_builtin() {
  local name="$1"
  for b in $COWORK_BUILTINS; do
    [[ "$name" == "$b" ]] && return 0
  done
  return 1
}

mkdir -p "$REPO" "$CANONICAL"

# Step 1: Migrate real (non-symlink) skill dirs from Cowork to repo
if [[ -d "$COWORK" ]]; then
  for cowork_skill in "$COWORK"/*/; do
    [[ ! -d "$cowork_skill" ]] && continue
    skill_name=$(basename "$cowork_skill")

    # Skip symlinks - already managed
    [[ -L "${cowork_skill%/}" ]] && continue

    # Skip Cowork built-ins
    if is_builtin "$skill_name"; then continue; fi

    # Migrate to repo if not already there
    if [[ ! -d "$REPO/$skill_name" ]]; then
      cp -r "$cowork_skill" "$REPO/$skill_name"
      log "Imported '$skill_name' from Cowork to repo"
    else
      log "Skipped import of '$skill_name' from Cowork - already in repo"
    fi

    # Remove original from Cowork
    rm -rf "$cowork_skill"

    # Ensure canonical symlink exists (repo -> canonical)
    if [[ ! -L "$CANONICAL/$skill_name" ]]; then
      [[ -d "$CANONICAL/$skill_name" ]] && rm -rf "$CANONICAL/$skill_name"
      ln -s "$REPO/$skill_name" "$CANONICAL/$skill_name"
      log "Linked repo/$skill_name -> canonical"
    fi

    # Create Cowork symlink (canonical -> cowork)
    ln -s "$CANONICAL/$skill_name" "${cowork_skill%/}"
    log "Linked canonical/$skill_name -> Cowork"
  done
fi

# Step 2: Migrate real (non-symlink) dirs from ~/.claude/skills/ to repo
for canonical_skill in "$CANONICAL"/*/; do
  [[ ! -d "$canonical_skill" ]] && continue
  skill_name=$(basename "$canonical_skill")

  # Skip if already a symlink - properly managed
  [[ -L "${canonical_skill%/}" ]] && continue

  # Real directory - migrate to repo
  if [[ ! -d "$REPO/$skill_name" ]]; then
    cp -r "$canonical_skill" "$REPO/$skill_name"
    log "Imported '$skill_name' from canonical to repo"
  else
    log "Skipped import of '$skill_name' from canonical - already in repo"
  fi

  # Replace with symlink
  rm -rf "$canonical_skill"
  ln -s "$REPO/$skill_name" "${canonical_skill%/}"
  log "Replaced canonical/$skill_name with symlink to repo"
done

# Step 3: Ensure all repo skills are symlinked in ~/.claude/skills/
for repo_skill in "$REPO"/*/; do
  [[ ! -d "$repo_skill" ]] && continue
  skill_name=$(basename "$repo_skill")
  canonical_target="$CANONICAL/$skill_name"

  if [[ ! -e "$canonical_target" ]]; then
    ln -s "$repo_skill" "$canonical_target"
    log "Linked new repo skill '$skill_name' -> canonical"
  fi
done

# Step 4: Ensure all canonical skills are symlinked in Cowork
if [[ -d "$COWORK" ]]; then
  for canonical_skill in "$CANONICAL"/*/; do
    [[ ! -d "$canonical_skill" ]] && continue
    skill_name=$(basename "$canonical_skill")
    cowork_target="$COWORK/$skill_name"

    if [[ ! -e "$cowork_target" ]]; then
      ln -s "${canonical_skill%/}" "$cowork_target"
      log "Linked canonical/$skill_name -> Cowork"
    fi
  done
fi

# Step 5: Clean up broken symlinks
for canonical_skill in "$CANONICAL"/*/; do
  skill_name=$(basename "$canonical_skill")
  if [[ -L "${canonical_skill%/}" && ! -e "${canonical_skill%/}" ]]; then
    rm "${canonical_skill%/}"
    log "Removed broken symlink '$skill_name' from canonical"
  fi
done

if [[ -d "$COWORK" ]]; then
  for cowork_skill in "$COWORK"/*/; do
    skill_name=$(basename "$cowork_skill")
    if [[ -L "${cowork_skill%/}" && ! -e "${cowork_skill%/}" ]]; then
      rm "${cowork_skill%/}"
      log "Removed broken symlink '$skill_name' from Cowork"
    fi
  done
fi

# Step 6: Log import reminders for any newly imported skills
for repo_skill in "$REPO"/*/; do
  [[ ! -d "$repo_skill" ]] && continue
  skill_name=$(basename "$repo_skill")
  # Check if tracked by git
  if ! git -C "$REPO/.." ls-files --error-unmatch "skills/$skill_name/SKILL.md" >/dev/null 2>&1; then
    log "ACTION NEEDED: '$skill_name' imported to repo but not yet committed - run: cd ~/dev/claude-workflows && git add skills/$skill_name && git commit"
  fi
done

log "Sync complete"
