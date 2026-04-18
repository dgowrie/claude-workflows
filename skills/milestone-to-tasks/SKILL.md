---
name: milestone-to-tasks
user-invocable: true
description: >
  Generate a structured tasks.json + progress.md from a GitHub milestone, ready for
  a Ralph-style loop. Use when user wants to convert a milestone into an LLM-friendly
  task list, set up a ralph loop against a milestone, or generate a work queue from
  GitHub issues.
---

# Milestone to Tasks

Convert a GitHub milestone into a structured `tasks.json` + seeded `progress.md` under `.claude/milestones/<slug>/`. The artifact is the contract consumed by `/work-next-task` (or any other worker skill that respects the schema).

`tasks.json` is a **living specification of the desired end state** — not a plan. Mid-flight edits (adding tasks, flipping `done → open` with revised steps, re-prioritizing) are first-class operations. The worker re-reads the file every iteration.

## Process

### 1. Resolve the milestone

Accept any of:

- Milestone number (e.g., `42`)
- Milestone URL (`https://github.com/org/repo/milestone/42`)
- Milestone title (`"Q2 auth cleanup"`)

Auto-detect the repo via `gh repo view` in the current directory. If not in a git repo, ask the user.

Slug the milestone title for file paths: `.claude/milestones/<slug>/`. If title is empty, use `milestone-<number>`.

### 2. Fetch the issues

```bash
gh issue list --milestone <ref> --state all \
  --json number,title,body,labels,state,url,assignees
```

Include closed issues — their state matters for initial `status` and future drift detection.

### 3. Infer priority and dependencies (hybrid)

Explicit signals first, LLM fallback, user confirms.

**Priority** — try in order:

1. Explicit labels: `P0`, `P1`, `P2`, `priority:*`, etc.
2. Dependency depth: root blockers get higher priority than leaves.
3. LLM inference from title/body.

**`blocked_by`** — try in order:

1. Parse explicit `Blocked by #N`, `Depends on #N` from issue bodies.
2. GitHub sub-issue / issue-link relations via `gh api`.
3. LLM inference from body content.

**`type`** (conventional commit): infer from labels (`type:feat`, `kind/bug`) or body keywords. Default `feat`.

**`category`** (Anthropic-style domain tag): infer from labels (`area:*`, `component:*`) or content. Default `functional`.

### 4. Quiz the user

Show the proposed structure before writing. Example:

```
Proposed task graph (7 issues):

  T1  P0  feat  #123  Fix widget null-children crash
          blocked_by: []
  T2  P1  feat  #124  Add widget empty state
          blocked_by: [T1]
  ...

Priority source:  labels (5), depth-inferred (2)
Dep source:       explicit refs (4), sub-issues (1), LLM-inferred (2)

Confirm graph, or edit before write?
```

Iterate until approved. Never silently commit LLM inferences for priority or deps.

### 5. Write `tasks.json`

Path: `.claude/milestones/<slug>/tasks.json`.

Schema:

```json
{
  "milestone": {
    "number": 42,
    "title": "Q2 auth cleanup",
    "url": "https://github.com/org/repo/milestone/42"
  },
  "generated_at": "2026-04-17T10:00:00Z",
  "config": {
    "max_retries_per_task": 3,
    "require_verification": true
  },
  "tasks": [
    {
      "id": "T1",
      "github_issue": 123,
      "title": "Fix widget null-children crash",
      "type": "feat",
      "category": "functional",
      "description": "Brief summary. Worker fetches canonical body from GH at pickup.",
      "priority": "P0",
      "status": "open",
      "blocked_by": [],
      "steps": [
        "Run failing test demonstrating null-children crash",
        "Confirm fix renders empty widget cleanly",
        "Verify regression test exists"
      ]
    }
  ]
}
```

Field notes:

- `id`: monotonic `T<n>`, stable across `--refresh`.
- `status`: pre-set to `done` if upstream GH issue is already closed (merged, won't-fix, duplicate).
- `description`: short summary, not a full duplicate of the issue body. Worker fetches canonical body via `gh issue view` on pickup.
- `steps`: explicit verification gates. Worker walks every step as an acceptance gate before flipping `status: done`. Vague steps lead to failure loops — be specific.
- `config.max_retries_per_task`: worker halts with `<promise>HALT</promise>` if a task has been `reverted to open` this many times.

### 6. Seed `progress.md`

Path: `.claude/milestones/<slug>/progress.md`. Append-only, reverse-chronological.

Initial entry:

```markdown
# Progress log — <milestone title>

## 2026-04-17 10:00 — generated
- Source: milestone #42 (7 issues)
- Generator: milestone-to-tasks
- Priority source: labels (5), depth (2)
- Dep source: explicit (4), sub-issues (1), LLM (2)
```

### 7. Configure git for concurrent-safe progress appends

Ensure `.gitattributes` at repo root contains:

```
.claude/milestones/*/progress.md merge=union
```

Enables clean auto-merge of concurrent progress appends across worktrees. Add only if missing.

### 8. Report output

```
Wrote:
  .claude/milestones/<slug>/tasks.json
  .claude/milestones/<slug>/progress.md
  .gitattributes (updated)

Next:
  /work-next-task                    one iteration
  scripts/ralph.sh                   full capital-R Ralph loop
  /loop /work-next-task              in-session loop (less Ralph-pure)
```

## Refresh mode

`/milestone-to-tasks --refresh` — conservative merge from upstream:

- Pull upstream milestone state.
- **Add** new issues as new tasks (new `T<n>` ids, fresh `status: open`, deps re-inferred and re-confirmed).
- **Update** `title`, `description`, `labels` on existing tasks.
- **Never touch** `status`, `blocked_by`, `priority`, `steps` on existing tasks — these are user-owned mid-flight.
- **Upstream closed → local `done`:** one-directional sync for issue closure.
- Append a refresh entry to `progress.md`.

`/milestone-to-tasks --force` — full regenerate:

- Rewrite `tasks.json` from upstream.
- Preserve `status` only (matched by `github_issue`).
- Lose hand-edits to priority / blocked_by / steps / description.
- Use when the upstream milestone has been substantially restructured.

## Related / future work

- **`prd-to-tasks` variant:** generate tasks.json from a PRD issue + its sub-issues, for repos that use PRD-with-subissues instead of milestones.
- **Running `/loop` directly against a PRD's sub-issue graph:** skip tasks.json entirely because deps/priorities are already encoded on the issues. Still uses `progress.md`. Separate related skill; does not replace this one.
- **Three-way merge for `--refresh`:** if conservative-merge produces surprises, compute upstream / local / common-ancestor diff with per-change confirmation.
- **Fully-unattended AFK/sandbox variant** (see `work-next-task` Related).
