---
name: memory-audit
description: >
  Review, consolidate, and prune a project's memory files. Merges duplicates, sharpens durable entries,
  retires dated ones, fixes relative time references, flags oversized files, surfaces promotion
  candidates for global CLAUDE.md, and tidies the `MEMORY.md` index. Defaults to the current project;
  offers a cross-project sweep after the main report; duplicated memories across projects are strong
  promotion signals.
  Trigger phrases: "audit memories", "consolidate memories", "tidy up memory", "clean up memories",
  "prune memories", "review memories", "merge memory files", "memory audit".
---

# Memory Audit

You are reviewing the user's Claude Code memory files for hygiene and consolidation. The goal is to keep memory lean, relevant, and well-described so that the two-tier loading system (index always loaded, files loaded on demand) works efficiently.

## Tone

This is a reflective pass, not just a checklist. As you evaluate, you're synthesizing what the user values, what's durable about how they work, and what belongs in future sessions. Separate the *durable* (preferences, working style, key relationships, recurring workflows) from the *dated* (specific projects, deadlines, one-off tasks). Keep and sharpen the durable; retire the dated or fold its lasting takeaway into a durable entry.

---

## Step 1: Discover memory locations

Default to the current project's memory directory. Identify it from your system prompt's auto-memory section, or from `$PWD` mapped under `~/.claude/projects/`. Read its `MEMORY.md` index and report the entry count.

A cross-project sweep is offered at the end of Step 4 (mechanics and rationale live there).

---

## Step 2: Read all indexes

Read each `MEMORY.md` file in scope. For each entry, note:
- The project scope it belongs to
- The one-line description
- The file it points to

---

## Step 3: Audit each memory file

Read each referenced memory file and evaluate against these criteria:

### Staleness / durable vs dated

Flag entries where:
- The `type: project` memory references a PR that has been merged or closed
- The memory references an issue that has been resolved
- The memory contains dates more than 30 days old with no ongoing relevance
- The subject of the memory is already reflected in the current codebase (check if applicable)
- The memory is *dated* (about a specific project, deadline, or one-off task) and its window has passed - consider retiring it, or fold its lasting takeaway (e.g. "user prefers X format for launch docs") into a durable entry before deleting

To verify PR/issue status, use:
```bash
gh pr view <number> --repo <owner/repo> --json state,mergedAt
gh issue view <number> --repo <owner/repo> --json state,closedAt
```

### Size

Flag any memory file exceeding 2KB. These likely belong in a plan, repo document, or code comment.

Report the file size for each memory.

### Time references

Flag memories containing relative date phrases ("next week", "this quarter", "by Friday") rather than absolute dates. Relative phrasing becomes unreadable weeks after the memory was written.

When proposing a conversion, anchor from the memory's reference point, *not today's date*: use an explicit timestamp in the memory body if one exists, otherwise the file's last-modification time. If the intended date remains ambiguous (e.g., the memory has been edited multiple times and the relative phrase could belong to any edit), do not guess - flag it and ask the user to confirm before suggesting a replacement.

### Easy to re-find elsewhere

Flag memories that merely restate information the user can pull from a calendar, docs, or connected tool on demand. Keep what's hard to re-derive: stated preferences, context behind a decision, who to go to for what.

### Index description quality

Flag descriptions that are vague or non-filterable. A good description names the specific feature, issue number, or domain. Examples of bad descriptions:
- "project context notes"
- "testing feedback"
- "user preferences"

### Duplicates and overlap

Flag entries that cover substantially the same ground within a scope. Propose merging into one file and keeping the richer file's path. On a cross-project sweep, duplicates *across* scopes are promotion candidates - see below.

### Promotion candidates

Flag `type: feedback` memories that represent behavioral rules applicable across projects. These should be promoted to global `~/.claude/CLAUDE.md` rather than staying project-scoped. On cross-project sweeps, a memory appearing in multiple projects is a strong promotion signal - even if the user hasn't explicitly said "this is global."

---

## Step 4: Report

Present findings in this format:

```
## Memory Audit — <date>

**Scope:** <current project | N projects, N total memories>

### Actions

#### Delete (stale / dated)
- `<project>/<file>` — <reason>

#### Resize (>2KB)
- `<project>/<file>` — <current size>, <suggestion>

#### Fix time references
- `<project>/<file>` — "<relative phrase>" → "<proposed absolute date>"

#### Drop (easy to re-find elsewhere)
- `<project>/<file>` — <reason>

#### Improve description
- `<project>/<file>` — current: "<description>" → suggested: "<better description>"

#### Merge
- `<project>/<file1>` + `<file2>` — <overlap description>

#### Promote to CLAUDE.md
- `<project>/<file>` — <rule summary>

### No action needed
- `<project>/<file>` — OK
```

If you ran on a single project only, end the report with an explicit offer:

> Want me to sweep all projects next? A memory that appears in multiple projects is a strong signal it belongs in global `CLAUDE.md` rather than any single project scope.

On accept, run:

```bash
find ~/.claude/projects -name "MEMORY.md" -type f
```

Report how many project scopes have memories and the total entry count, then loop back through Steps 2-4 with the expanded scope before moving to Step 5.

---

## Step 5: Execute

After presenting the report, ask which actions the user wants to take. Then execute them:

- **Delete**: Remove the memory file and its `MEMORY.md` index entry
- **Resize**: Propose a trimmed version of the file for user approval
- **Fix time references**: Update the memory file to replace relative dates with absolute ones
- **Drop (easy to re-find elsewhere)**: Remove the memory file and its `MEMORY.md` index entry
- **Improve description**: Update the `MEMORY.md` index entry
- **Merge**: Combine files, update index, delete the redundant file
- **Promote**: Propose the CLAUDE.md addition, apply on confirmation, then delete the memory

Always confirm before making changes. Present a summary of what was done at the end.
