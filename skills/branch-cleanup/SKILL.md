---
name: branch-cleanup
user-invocable: true
description: >
  Interactive local branch cleanup. Reviews all local branches, cross-references with merged PRs
  and remote state, categorizes by status, and walks the user through deletions and pruning.
  Trigger phrases: "clean up branches", "branch cleanup", "prune branches", "delete old branches",
  "tidy up branches".
---

# Branch Cleanup

You are performing an interactive review of the user's local git branches. The goal is to identify
branches that are safe to delete (merged), branches that should be kept (open PRs), and branches
that need the user's judgment (stale WIP, no PR).

---

## Step 1: Gather state

First, update remote tracking info so categorization is based on current state:
```bash
git fetch --prune
```

Then run these commands in parallel:

```bash
# Local branches with tracking info
git branch -vv

# Stale remote tracking refs (already pruned by fetch, but confirm none remain)
git remote prune origin --dry-run

# Recent main/base branch history (for merge cross-reference)
git log main --oneline -30

# Merged PRs by current user
gh pr list --state merged --author @me --limit 100 --json number,title,headRefName

# Open PRs by current user (for bulk cross-reference in Step 2)
gh pr list --state open --author @me --json number,title,headRefName
```

Note: the `--limit 100` on merged PRs won't catch branches from very old PRs. If branches
appear in the "WIP / no PR" category but the user recognizes them as previously merged, they
can confirm deletion manually. Bumping the limit helps but isn't a complete solution.

If the default branch is not `main`, detect it first:
```bash
git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
```

---

## Step 2: Categorize branches

For each local branch (excluding the current branch), classify it:

### Merged — safe to delete
The branch's corresponding PR has been merged. Confirm by matching `headRefName` from the merged
PR list. Also check `git branch --merged <base>` as a secondary signal, though squash-merged
branches won't appear there.

### Open PR — keep
The branch has an open PR. Match by `headRefName` from the open PR list gathered in Step 1.
If a branch doesn't match the bulk list (e.g., authored by someone else), fall back to:
```bash
gh pr list --state open --head <branch-name> --json number,state,title
```

Note if the branch is significantly behind the base branch (>10 commits behind).

### WIP / no PR — user's call
No matching PR (merged or open). Flag these for the user's judgment. Include:
- Last commit date and message
- Whether a remote branch exists
- How far ahead/behind the base branch it is

To get the last commit date:
```bash
git log -1 --format="%cr - %s" <branch-name>
```

---

## Step 3: Present the review

Use this format:

```
### Safe to delete (merged PRs)

| Branch | Merged PR |
| --- | --- |
| `<branch>` | #<number> |

### Open PRs (keep)

| Branch | PR |
| --- | --- |
| `<branch>` | #<number> (open) |

### WIP / no PR (your call)

| Branch | Notes |
| --- | --- |
| `<branch>` | <last commit info, ahead/behind, remote status> |
```

If there are stale remote tracking refs, report the count and list them.

After presenting, ask the user what they want to do. Do not delete anything without confirmation.

---

## Step 4: Execute

Based on user instructions, perform the requested actions:

- **Delete merged branches**: `git branch -D <branch1> <branch2> ...`
- **Prune stale remote refs**: `git remote prune origin`
- **Delete WIP branches**: Only when the user explicitly names them

Report what was deleted and show the remaining branch list when done.

---

## Notes

- Always use `git branch -D` (force delete) rather than `-d` for merged branches. Squash-merged
  branches won't be recognized as merged by `-d` since the commits differ.
- Never delete the current branch. If the user is on a branch they want to delete, ask them to
  switch first.
- Never force-push, reset, or modify branch contents. This skill only deletes local branches and
  prunes stale remote refs.
- If the user has branches from other contributors (not `@me`), include them in the WIP category
  and note the author.
