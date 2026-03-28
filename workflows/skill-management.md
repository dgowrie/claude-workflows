# Skill Management Workflow

How custom Claude Code skills are created, stored, deployed, and synced across all surfaces.

---

## Architecture: Three-Tier Skill Sync

```
~/dev/claude-workflows/skills/   (Tier 1 - source of truth, git-tracked)
        |
        | symlinks
        v
~/.claude/skills/                (Tier 2 - deployment, all surfaces read this)
        |
        | symlinks
        v
$COWORK_SKILLS/                  (Tier 3 - Cowork bridge)
```

All user-created skills live as real directories in the repo (Tier 1). The other two tiers contain only symlinks. Edits to a skill in any surface modify the same file.

---

## Surfaces and Access

| Surface | Reads skills from | How |
| --- | --- | --- |
| Terminal CLI | `~/.claude/skills/` | Direct (symlinks to repo) |
| VS Code extension | `~/.claude/skills/` | Direct (symlinks to repo) |
| Claude desktop - Code mode | `~/.claude/skills/` | Direct (symlinks to repo) |
| Claude desktop - Cowork mode | `$COWORK_SKILLS/` | Symlinks to `~/.claude/skills/` |

All surfaces resolve to the same physical files in the repo through the symlink chain.

---

## Skill Creation Flows

### Created in the repo (preferred)

1. Create `skills/<name>/SKILL.md` in `~/dev/claude-workflows/`
2. Commit to git
3. The sync script auto-creates symlinks in `~/.claude/skills/` and Cowork
4. Skill is immediately available everywhere

### Created in Claude Code CLI or manually

1. Skill lands as a real directory in `~/.claude/skills/`
2. Sync script detects the non-symlink directory
3. Copies it to `~/dev/claude-workflows/skills/`
4. Replaces the original with a symlink to the repo copy
5. Creates a Cowork symlink
6. Logs a reminder to commit: check `~/.claude/sync-skills.log`

### Created in Cowork (via skill-creator)

1. Cowork writes the skill as a real directory in `$COWORK_SKILLS/`
2. Sync script detects it (skipping built-in skills)
3. Copies it to `~/dev/claude-workflows/skills/`
4. Removes the Cowork original, replaces with symlink chain
5. Logs a reminder to commit

---

## Sync Infrastructure

Both the sync script and launchd plist are version-controlled in this repo under `workflows/sync/`. The deployed locations are symlinks:

```
workflows/sync/sync-skills.sh           -> ~/.claude/sync-skills.sh
workflows/sync/com.claude.sync-skills.plist -> ~/Library/LaunchAgents/com.claude.sync-skills.plist
```

To set up on a fresh machine, create the symlinks and load the watcher:

```bash
ln -s ~/dev/claude-workflows/workflows/sync/sync-skills.sh ~/.claude/sync-skills.sh
ln -s ~/dev/claude-workflows/workflows/sync/com.claude.sync-skills.plist ~/Library/LaunchAgents/com.claude.sync-skills.plist
launchctl load ~/Library/LaunchAgents/com.claude.sync-skills.plist
```

## Sync Script

**Source:** `workflows/sync/sync-skills.sh`
**Deployed at:** `~/.claude/sync-skills.sh` (symlink)

**What it does on each run:**
1. Migrates real dirs from Cowork to repo (skipping built-ins: docx, pdf, pptx, schedule, skill-creator, xlsx)
2. Migrates real dirs from `~/.claude/skills/` to repo
3. Ensures all repo skills are symlinked in `~/.claude/skills/`
4. Ensures all canonical skills are symlinked in Cowork
5. Cleans up broken symlinks in both locations
6. Logs import reminders for uncommitted skills

**Log:** `~/.claude/sync-skills.log`

**Manual run:**
```bash
~/.claude/sync-skills.sh
```

---

## launchd Watcher

**Source:** `workflows/sync/com.claude.sync-skills.plist`
**Deployed at:** `~/Library/LaunchAgents/com.claude.sync-skills.plist` (symlink)

**How it works:** This is NOT a persistent daemon. launchd is a macOS system service that registers the plist and uses kernel-level filesystem monitoring (kqueue/FSEvents) to watch the three skill directories. Between triggers, nothing is running - zero CPU, zero memory. When a directory entry changes, macOS spawns the script, it runs for ~100ms, then exits.

**Triggers:**
- On login (RunAtLoad) - catches changes made while the machine was off
- On directory change (WatchPaths) - fires when entries are added/removed in any of the three skill directories

**Management:**
```bash
# Check if registered (does not mean actively running)
launchctl list | grep claude

# Reload after plist changes
launchctl unload ~/Library/LaunchAgents/com.claude.sync-skills.plist
launchctl load ~/Library/LaunchAgents/com.claude.sync-skills.plist

# Stop watching entirely
launchctl unload ~/Library/LaunchAgents/com.claude.sync-skills.plist

# Monitor
tail -f ~/.claude/sync-skills.log
```

---

## Hardcoded Paths and Portability

The sync script and plist contain absolute paths with the username (e.g., `/Users/dggraf/`). This is a portability concern, not a security concern:

- **Not sensitive** - the username is visible to any process on the machine; launchd agents in `~/Library/LaunchAgents/` are user-scoped by definition (only your user can load or see them)
- **Not shared** - the paths point to your own config directories, running under your own account
- **Portability** - if this repo is shared or used on another machine, the paths need updating. If that becomes needed, the script and plist could be templated (replace `/Users/dggraf` with a placeholder, generate the real files during setup)

For now, hardcoded paths are the simplest correct approach for a single-machine setup.

---

## Known Limitations

- **Cowork UUID stability** - the two UUIDs in the Cowork path are stable as of Mar 2026. If Anthropic changes them, update the path in both `sync-skills.sh` and the plist. Symptom: skills stop appearing in Cowork.
- **WatchPaths granularity** - launchd fires on directory-level changes (entries added/removed), not file content edits within a skill. This is fine since content edits don't require sync.
- **Cowork built-ins skip list** - hardcoded in the sync script. If Cowork adds new built-in skills, add them to the `COWORK_BUILTINS` variable.
- **Git commit is manual** - the sync script imports files but does not commit. Check the log for ACTION NEEDED reminders.
- **Workaround status** - Anthropic issue #20697 tracks native unified skill storage. When that ships, the Cowork bridge (Tier 3) can be retired.
