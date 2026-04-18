---
name: work-next-task
user-invocable: true
description: >
  Run one iteration of a ralph loop against a tasks.json file — pick the next unblocked
  highest-priority task, do the work, verify, commit, update status + progress log. Use
  when user wants to advance a task list, pick up the next task, or step a ralph loop.
---

# Work Next Task

One iteration of a ralph loop over `.claude/milestones/<slug>/tasks.json`. Pick, work, verify, commit, exit.

Composes with:

- `/loop /work-next-task` — in-session convenience (carries session context, less Ralph-pure)
- `scripts/ralph.sh` — headless shell harness for capital-R Ralph runs (fresh process per iteration, file-only state)

## Contract

**Inputs:** `.claude/milestones/<slug>/tasks.json` + `.claude/milestones/<slug>/progress.md`. Must already exist — run `/milestone-to-tasks` first.

**Default mode:** standard (single-worker, local-only). `--autonomous` enables push + draft PR + multi-worker discipline.

**Mutation surface in `tasks.json`:** only `status` on a single task per iteration. Nothing else is touched. The user owns `priority`, `blocked_by`, `steps`, `description` — these are the living spec.

**progress.md discipline:** prepend new entries at the **top** (reverse-chronological). **Never edit or delete existing entries.** The two-commit discipline and `git diff` review catch violations.

## Iteration

### 1. Find and load context

Locate `.claude/milestones/<slug>/tasks.json`. If multiple `<slug>` directories exist, ask the user (or accept `--slug`).

Read `tasks.json` and the top ~20 entries from `progress.md`.

### 2. Fetch (autonomous mode only)

```bash
git fetch
git rebase origin/<current-branch>
```

Ensures peer workers' status flips and claims are visible before selecting. Shrinks the race window.

### 3. Select

Find tasks where:

- `status == "open"`, AND
- All `blocked_by` ids have `status == "done"`

Among candidates, pick highest `priority` (P0 > P1 > P2). Tiebreak: lowest `id`.

**Retry-cap check:** before committing to the task, count recent `reverted to open` entries for its id in `progress.md`. If count >= `config.max_retries_per_task`, skip the task and halt:

- Append drift/halt entry to progress.md
- Emit `<promise>HALT</promise>` with reason "T<id> exceeded retry cap, needs human review"

**No candidates:**

- If ALL tasks have `status: done` → prompt for cleanup (step 9), then emit `<promise>MILESTONE_COMPLETE</promise>`.
- Otherwise → emit `<promise>HALT</promise>` with reason "no unblocked tasks; waiting on in_progress tasks".

### 4. Drift check

```bash
gh issue view <github_issue> --json title,state
```

Compare upstream `title` and `state` to the tasks.json entry. If `state: closed` upstream, halt:

- Append drift entry to progress.md
- Emit `<promise>HALT</promise>` with reason "drift detected on T<id>"

Body changes are expected (maintainers edit descriptions). Do not treat as drift.

### 5. Claim

- Checkout branch `<user>/<type>_T<id>-<slug>` (create if needed). `<user>` from `gh api user -q .login`. `<type>` from the task entry. `<slug>` kebab-cased from task title.
- Update `tasks.json`: set `status: in_progress` on the selected task **only**.
- Append pickup entry to `progress.md` (template below).
- Commit: `chore(tasks): T<id> open → in_progress`.

**Autonomous only:** push the claim commit immediately so peer workers see it on their next fetch.

### 6. Work

Read the canonical GH issue body via `gh issue view <github_issue>`. Implement the change end-to-end. Use the task's `description` + `steps` as the spec. Everything below that level (approach, file layout, ordering) is yours to decide.

### 7. Verify

Walk every item in the task's `steps[]` as an acceptance gate. If any step fails:

- Do **not** commit code changes.
- Revert `status: in_progress → open` in tasks.json.
- Append failure entry to progress.md (template below).
- Commit: `chore(tasks): T<id> reverted to open`.
- **Autonomous only:** push the revert commit.
- Exit silently (no completion token). Normal iteration — loop continues.

If all steps pass, continue.

### 8. Commit (success path)

Two discrete commits per iteration:

1. **Code commit:** `<type>(<scope>): <summary> (refs T<id>, #<github_issue>)`
2. **Task update commit:** `chore(tasks): T<id> → done`
   - Flip `status: done` in tasks.json.
   - Append success entry to progress.md.
   - Stage tasks.json and progress.md together.

**Autonomous only:** push the branch. Open a draft PR:

```bash
gh pr create --draft \
  --title "<type>: <summary>" \
  --body "Closes #<github_issue>

Part of milestone task T<id>."
```

Include the PR number in the progress entry.

### 9. Check for completion

If ALL tasks in `tasks.json` now have `status: done`, prompt:

> All tasks complete. Delete `.claude/milestones/<slug>/`? (y/N)

- **On confirmation:** delete the directory, commit `chore(tasks): cleanup completed milestone <slug>`, emit `<promise>MILESTONE_COMPLETE</promise>`.
- **On decline:** emit `<promise>MILESTONE_COMPLETE</promise>` anyway; artifacts remain for inspection.

### 10. Exit

Normal exit — no completion token. The harness continues to the next iteration.

## Exit / completion tokens

The skill emits one of these tokens in its final output so the shell harness can grep for them:

| Token | Meaning | Harness action |
|---|---|---|
| `<promise>MILESTONE_COMPLETE</promise>` | All tasks done | exit 0 |
| `<promise>HALT</promise>` | Drift, retry cap, or no unblocked tasks | exit 1 (human review) |
| (silent) | Normal one-task iteration complete | continue loop |

## Exit conditions (five)

1. Completed one task successfully → exit silently, loop continues.
2. Step verification failed → revert to `open`, exit silently, loop continues.
3. No unblocked tasks available → emit `HALT`.
4. All tasks done → prompt cleanup, emit `MILESTONE_COMPLETE`.
5. Drift detected OR retry cap exceeded → emit `HALT`.

## Progress.md entry templates

Use these templates verbatim (with values substituted). Structure keeps the log scannable.

**Pickup** (`open → in_progress`):

```markdown
## <iso-timestamp> — T<id>: open → in_progress
**Task:** <title> (GH #<n>)
**Drift check:** <none | flagged: details>
**Plan:** <approach>
```

**Success** (`in_progress → done`):

```markdown
## <iso-timestamp> — T<id> → done
**Completed:** <title> (GH #<n>)
**Files changed:** <list>
**Decisions:** <key calls and why>
**Blockers encountered:** <or "none">
**PR:** #<n>   <!-- autonomous only -->
**Next unblocked:** <ids>
**Notes for next iteration:** <optional>
```

**Failure** (`in_progress → open`):

```markdown
## <iso-timestamp> — T<id>: reverted to open
**What failed:** step <N> — <detail>
**Context:** <what was tried>
**Suggested next move:** <optional hint for next agent>
```

**Drift / halt**:

```markdown
## <iso-timestamp> — T<id>: drift detected, halted
**Upstream change:** <what differs>
**Action required:** <human review direction>
```

## Modes

| Mode | Workers | Fetch before select | Push claim | Push code + draft PR |
|---|---|---|---|---|
| standard (default) | 1 (by contract) | optional hygiene | N/A | no |
| `--autonomous` | N | required | required | required |

**Standard mode is single-worker by contract.** Two standard-mode workers in separate worktrees against the same `tasks.json` will race and double-claim. For multi-worker runs, use `--autonomous` on all of them. Mixing is not supported.

## Mid-flight spec edits

`tasks.json` is a living spec. Expected user edits **between** iterations:

- Flip a `done` task back to `open` with revised `steps` or `description` when the first pass wasn't right.
- Add a new task (next monotonic `T<n>`) with `status: open`.
- Adjust `priority` or `blocked_by` as understanding evolves.
- Tighten `steps` to make acceptance gates more specific.

The worker re-reads the file at the start of every iteration. No refresh command needed for local edits. For upstream (GitHub milestone) changes, run `/milestone-to-tasks --refresh`.

## Related / future work

- **v1.1 soft safety check:** at iteration start, `git log -5 --format=%s .claude/milestones/<slug>/tasks.json` across branches; warn if another branch has recently modified the file. Catches "forgot another worker was running."
- **Advisory claim files** (`claims/<agent-id>.json` with heartbeat): if fetch-before-select / push-after-claim proves insufficient under load.
- **Fully-unattended AFK / sandbox variant:** Docker isolation; network scoping to git remote + GH API only; GH token mounted with minimum scope; CPU / mem / disk quotas; wall-clock timeout in addition to `max_retries_per_task`; cost/token budget; crash-recovery discipline for mid-iteration process death; per-iteration log capture at `.claude/milestones/<slug>/logs/<iso>.log`; `AFK` skill integration for halt / completion notifications; explicit transient-vs-logic failure policy.
- **CI watch inside the autonomous loop** instead of composing with separate conventions.
- **Alternative source skill** running directly against a PRD's sub-issue graph, skipping tasks.json.
