---
name: session-wrapup
description: >
  Two checks to run at the natural end of a substantive session, before ending it: a quick
  memory-staleness audit (not the deep dive that the memory-audit skill does) and a scan for
  residual repo/disk/process state worth surfacing (worktrees, stale branches, background
  processes, temp files, stray uncommitted changes). Trigger phrases: the user says "done",
  "thanks", "that's it", or similar, or the task is complete and nothing is left to do, or
  explicit `/session-wrapup`.
---

# Session Wrapup

Before ending any session where substantive work occurred, run both checks below. Skip for
trivial sessions (quick questions, no code changes, no decisions made).

## 1. Memory audit

Audit the project's memory files.

### Audit steps

1. **Identify relevant memories.** Read `MEMORY.md`'s index; open any memory file whose
   description overlaps with this session's work.
2. **Check for staleness.** A memory is stale if:
   - It describes state that changed (scope shifted, question resolved, approach abandoned).
   - It references artifacts that were renamed, moved, or deleted.
   - It contains "TODO" or "open question" items that were resolved.
3. **Check for consolidation opportunities.** Flag memories that overlap significantly or could
   merge into one.
4. **Check for obsolete memories.** Flag memories for work that shipped, was abandoned, or is no
   longer relevant.

For a deep, project-wide consolidation pass rather than this session's quick check, use the
`memory-audit` skill instead.

### Actions

**Non-destructive (update in place, no confirmation needed):**
- Update stale facts, resolved questions, corrected scope.
- Fix broken references (renamed files, moved paths).
- Update `MEMORY.md` index descriptions to match revised content.

**Destructive (prompt user before proceeding):**
- Deleting memory files (obsolete, shipped, abandoned).
- Merging/consolidating multiple files into one (deletes originals).

### Output

End with a compact summary:

```
Memory audit:
- Updated N: name1 (brief reason), name2 (brief reason)
- Removed N: name1 (brief reason), name2 (brief reason)
- No changes needed / Skipped (trivial session)
```

No other commentary. If nothing changed, say so in one line and move on.

## 2. Housekeeping scan

Proactively scan for and surface residual state the user might want to clean up. Separate from
the memory audit above, this covers repo/disk/process leftovers.

### What to surface

- Locked or leftover git worktrees from agents or `--worktree` sessions.
- Unmerged feature branches that are now stale (merged PR, or superseded).
- Background processes still running.
- Temp files created during the session.
- Uncommitted changes in unexpected places.

### How to apply

- Do a quick check: `git worktree list`, backgrounded processes, temp files created this
  session, and branches that can be deleted.
- Mention each briefly with the specific cleanup command. Do NOT execute destructive cleanup
  without confirmation; just surface the option.

### Worktree remnants

`git worktree remove` does not clean up gitignored directories like `node_modules/` and `dist/`.
After confirming a worktree is gone from `git worktree list`, also check whether its directory
still exists on disk (especially under `.claude/worktrees/`); if it does, offer to `rm -rf` the
leftover. Applies to both subagent worktrees and `--worktree` session worktrees.

### Why

The user asked for this proactively after a leftover agent worktree was flagged. It reduces the
cognitive load of remembering cleanup across sessions and avoids disk/repo cruft accumulating.
