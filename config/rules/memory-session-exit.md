# Session Exit: Memory Audit

Before ending any session where substantive work occurred, audit the project's memory files. Skip for trivial sessions (quick questions, no code changes, no decisions made).

## Trigger

When wrapping up - recognizable by: user says "done"/"thanks"/"that's it"/similar, or the task is complete and there's nothing left to do.

## Audit Steps

1. **Identify relevant memories.** Read `MEMORY.md` index; open any memory file whose description overlaps with this session's work.
2. **Check for staleness.** Compare each relevant memory's content against what actually happened this session. A memory is stale if:
   - It describes state that changed (scope shifted, question resolved, approach abandoned)
   - It references artifacts that were renamed, moved, or deleted
   - It contains "TODO" or "open question" items that were resolved
3. **Check for consolidation opportunities.** Flag memories that overlap significantly or could merge into one.
4. **Check for obsolete memories.** Flag memories for work that shipped, was abandoned, or is no longer relevant.

## Actions

**Non-destructive (update in place, no confirmation needed):**
- Update stale facts, resolved questions, corrected scope
- Fix broken references (renamed files, moved paths)
- Update MEMORY.md index descriptions to match revised content

**Destructive (prompt user before proceeding):**
- Deleting memory files (obsolete, shipped, abandoned)
- Merging/consolidating multiple files into one (deletes originals)

## Output

End with a compact summary:

```
Memory audit:
- Updated N: name1 (brief reason), name2 (brief reason)
- Removed N: name1 (brief reason), name2 (brief reason)
- No changes needed / Skipped (trivial session)
```

No other commentary. If nothing changed, say so in one line and move on.
