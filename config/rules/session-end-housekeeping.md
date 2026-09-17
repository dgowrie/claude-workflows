# Session-End Housekeeping

At natural session endings (the user signals done/thanks/an explicit pause, or the task is complete), proactively scan for and surface residual state the user might want to clean up. This is separate from the memory audit in `memory-session-exit.md` (which covers memory files); this rule covers repo/disk/process leftovers.

## What to surface

- Locked or leftover git worktrees from agents or `--worktree` sessions.
- Unmerged feature branches that are now stale (merged PR, or superseded).
- Background processes still running.
- Temp files created during the session.
- Uncommitted changes in unexpected places.

## How to apply

- Before wrapping up, do a quick check: `git worktree list`, backgrounded processes, temp files created this session, and branches that can be deleted.
- Mention each briefly with the specific cleanup command. Do NOT execute destructive cleanup without confirmation; just surface the option.

## Worktree remnants

`git worktree remove` does not clean up gitignored directories like `node_modules/` and `dist/`. After confirming a worktree is gone from `git worktree list`, also check whether its directory still exists on disk (especially under `.claude/worktrees/`); if it does, offer to `rm -rf` the leftover. Applies to both subagent worktrees and `--worktree` session worktrees.

## Why

The user asked for this proactively after a leftover agent worktree was flagged. It reduces the cognitive load of remembering cleanup across sessions and avoids disk/repo cruft accumulating.
