---
name: memory-audit
description: >
  Review and prune memory files across all Claude Code projects. Flags stale entries, oversized files,
  vague index descriptions, and candidates for CLAUDE.md promotion. Use this skill periodically to
  keep memory lean and effective. Trigger phrases: "audit memories", "clean up memories", "memory audit",
  "prune memories", "review memories".
---

# Memory Audit

You are reviewing the user's Claude Code memory files for hygiene issues. The goal is to keep memory
lean, relevant, and well-described so that the two-tier loading system (index always loaded, files
loaded on demand) works efficiently.

---

## Step 1: Discover all memory locations

Find every `MEMORY.md` index file across all project scopes:

```bash
find ~/.claude/projects -name "MEMORY.md" -type f
```

Report how many project scopes have memories and the total entry count across all indexes.

---

## Step 2: Read all indexes

Read each `MEMORY.md` file. For each entry, note:
- The project scope it belongs to
- The one-line description
- The file it points to

---

## Step 3: Audit each memory file

Read each referenced memory file and evaluate against these criteria:

### Staleness

Flag entries where:
- The `type: project` memory references a PR that has been merged or closed
- The memory references an issue that has been resolved
- The memory contains dates more than 30 days old with no ongoing relevance
- The subject of the memory is already reflected in the current codebase (check if applicable)

To verify PR/issue status, use:
```bash
gh pr view <number> --repo <owner/repo> --json state,mergedAt
gh issue view <number> --repo <owner/repo> --json state,closedAt
```

### Size

Flag any memory file exceeding 2KB. These likely belong in a plan, repo document, or code comment.

Report the file size for each memory.

### Index description quality

Flag descriptions that are vague or non-filterable. A good description names the specific feature,
issue number, or domain. Examples of bad descriptions:
- "project context notes"
- "testing feedback"
- "user preferences"

### Duplicates and overlap

Flag entries that cover substantially the same ground. Propose merging into one.

### Promotion candidates

Flag `type: feedback` memories that represent behavioral rules applicable across projects. These
should be promoted to the global `~/.claude/CLAUDE.md` rather than staying project-scoped.

---

## Step 4: Report

Present findings in this format:

```
## Memory Audit — <date>

**Scope:** <N> projects, <N> total memories

### Actions

#### Delete (stale)
- `<project>/<file>` — <reason>

#### Resize (>2KB)
- `<project>/<file>` — <current size>, <suggestion>

#### Improve description
- `<project>/<file>` — current: "<description>" → suggested: "<better description>"

#### Merge
- `<project>/<file1>` + `<file2>` — <overlap description>

#### Promote to CLAUDE.md
- `<project>/<file>` — <rule summary>

### No action needed
- `<project>/<file>` — OK
```

---

## Step 5: Execute

After presenting the report, ask which actions the user wants to take. Then execute them:

- **Delete**: Remove the memory file and its MEMORY.md index entry
- **Resize**: Propose a trimmed version of the file for user approval
- **Improve description**: Update the MEMORY.md index entry
- **Merge**: Combine files, update index, delete the redundant file
- **Promote**: Propose the CLAUDE.md addition, apply on confirmation, then delete the memory

Always confirm before making changes. Present a summary of what was done at the end.
