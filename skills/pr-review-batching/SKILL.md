---
name: pr-review-batching
user-invocable: true
description: >
  Stages PR review comments as drafts on a GitHub pending review; never publishes. Owns two
  operations: (1) ensure-then-append, which adds comments to an existing pending review or
  creates one if none exists, without clobbering user-in-flight edits; (2) incident response,
  which undoes an accidentally published review by deleting its visible comments and
  recreating as pending.

  ACTION-BOUNDARY TRIGGER: consult this skill before any `gh pr review` invocation or any
  POST / DELETE on `/pulls/{n}/reviews`. This skill is the guard against publishing a review
  when the user wanted drafts. Also triggers on phrases: "draft comment", "pending review",
  "post this as a draft", "add to the review", "stage as a draft", or explicit
  `/pr-review-batching`.
---

# PR Review Batching

This skill owns the submission lifecycle for PR review comments. Every comment is staged as a
draft on a pending review; the user submits manually. Claude never sets `event=COMMENT`,
`event=APPROVE`, or `event=REQUEST_CHANGES`.

Documented user convention (global `CLAUDE.md`):

> Never post comments individually. Use pending review mechanism.
> Present batch for confirmation; I submit manually to control review event type.

---

## Hard rules

1. **Never submit a review.** Do not pass an `event` field on POST to
   `/pulls/{n}/reviews`, and do not call `gh pr review` with `--comment`, `--approve`, or
   `--request-changes`. Omitting `event` keeps the review in state `PENDING`.
2. **Never PATCH an existing draft comment.** `PATCH /pulls/comments/{id}` is a blind
   overwrite of whatever the user may be editing in the browser. Use delete-and-recreate.
3. **Line numbers come from the file at the PR head SHA**, not diff offsets. Verify with
   `gh api repos/{owner}/{repo}/contents/{path}?ref={head_sha}` if unsure.
4. **Server is the source of truth.** Always sync from server before appending. The user may
   have edited drafts in the browser since the last Claude-side write.

---

## Operation 1: ensure-then-append

Use this flow to "add these N draft comments to the PR's pending review."

### Step 1. Detect existing pending review

```bash
gh api repos/{owner}/{repo}/pulls/{n}/reviews \
  --jq '.[] | select(.state=="PENDING") | .id'
```

Outcomes:

- **No output:** no pending review exists. Go to Step 2a.
- **One id:** pending review exists. Go to Step 2b.
- **Multiple ids:** unexpected. Stop and report to the user.

### Step 2a. Create pending review (no existing)

Write the accumulator to `/tmp/pr-review-batching-<pr-number>.json` in the shape below, then POST:

```bash
gh api repos/{owner}/{repo}/pulls/{n}/reviews \
  --method POST \
  --input /tmp/pr-review-batching-<pr-number>.json
```

Accumulator shape:

```json
{
  "comments": [
    {
      "path": "src/foo.ts",
      "start_line": 10,
      "line": 15,
      "start_side": "RIGHT",
      "side": "RIGHT",
      "body": "..."
    }
  ]
}
```

For single-line comments, omit `start_line` and `start_side`. Do NOT include an `event` field.

On success, delete the accumulator file. On failure, preserve it for debug.

### Step 2b. Append to existing pending review (delete-and-recreate)

GitHub has no safe idempotent append, so the append path is delete-and-recreate. Before doing
anything, check whether the existing review has any comments:

```bash
gh api repos/{owner}/{repo}/pulls/{n}/reviews/{review_id}/comments --jq 'length'
```

If `0`: fall through to Step 2a (no race window, nothing to preserve).

If `>= 1`: announce to the user (see Race-window protocol), then:

1. **Fetch comment metadata via REST** (bodies, node_ids, paths):

   ```bash
   gh api repos/{owner}/{repo}/pulls/{n}/reviews/{review_id}/comments
   ```

   REST omits `startLine`/`line` for pending comments, so metadata from REST alone is
   incomplete for multi-line comments.

2. **Enrich each via GraphQL** to recover the multi-line span:

   ```bash
   gh api graphql -f query='
     query($id: ID!) {
       node(id: $id) {
         ... on PullRequestReviewComment {
           path
           line
           startLine
           side
           startSide
           body
         }
       }
     }' -f id=<node_id>
   ```

3. **Build the accumulator** at `/tmp/pr-review-batching-<pr-number>.json` from the GraphQL
   output, translating field names to the REST review-comment payload schema. Preserve every
   body verbatim, including any `\r\n` line endings; do not normalize. This captures whatever
   edits the user made in the browser.

   Required field mapping (GraphQL camelCase -> REST snake_case):

   - `path` -> `path`
   - `line` -> `line`
   - `side` -> `side`
   - `body` -> `body`
   - `startLine` -> `start_line`
   - `startSide` -> `start_side`

   Omission rules for single-line comments: GraphQL returns `startLine: null` and
   `startSide: null`. Omit `start_line` and `start_side` entirely from the accumulator object.
   Do NOT send them as `null`, and do NOT leave them as camelCase keys.

   Example accumulator entries built from GraphQL results:

   ```json
   {
     "comments": [
       {
         "path": "src/example.ts",
         "start_line": 18,
         "line": 20,
         "start_side": "RIGHT",
         "side": "RIGHT",
         "body": "Existing multi-line draft"
       },
       {
         "path": "src/example.ts",
         "line": 42,
         "side": "RIGHT",
         "body": "Existing single-line draft"
       }
     ]
   }
   ```

4. **Append the new comment(s)** to the accumulator's `comments` array.

5. **Delete the pending review.** This only works while state is still `PENDING`:

   ```bash
   gh api -X DELETE repos/{owner}/{repo}/pulls/{n}/reviews/{review_id}
   ```

6. **POST the new pending review** with the full accumulator:

   ```bash
   gh api repos/{owner}/{repo}/pulls/{n}/reviews \
     --method POST \
     --input /tmp/pr-review-batching-<pr-number>.json
   ```

   No `event` field.

7. **On success:** delete `/tmp/pr-review-batching-<pr-number>.json`. On failure: leave it in
   place for debug inspection.

8. **Announce done** to the user (see Race-window protocol).

---

## Operation 2: incident response

Use when a review was accidentally submitted (state `COMMENTED`, `APPROVED`, or
`CHANGES_REQUESTED`) instead of staged as drafts.

### Step 1. Locate the published review

```bash
gh api repos/{owner}/{repo}/pulls/{n}/reviews \
  --jq '.[] | select(.state != "PENDING") | select(.user.login == "<current-user>") | .id'
```

### Step 2. Save the review's comments

Before deleting anything, fetch bodies and positional metadata:

```bash
gh api repos/{owner}/{repo}/pulls/{n}/reviews/{review_id}/comments
```

Enrich each via the GraphQL `node(id: ...)` query from Operation 1 Step 2b.2.

Build the standard accumulator at `/tmp/pr-review-batching-<pr-number>.json`.

### Step 3. Delete the visible inline comments

For each comment id:

```bash
gh api -X DELETE repos/{owner}/{repo}/pulls/comments/{comment_id}
```

### Step 4. Recreate as pending

Run Operation 1 with the saved accumulator.

### Step 5. Notify the user honestly

The published review record itself cannot be deleted; only its inline comments can. The empty
review shell (with its state and timestamp) remains on the PR timeline. Surface this:

> Inline comments from the published review have been removed and recreated as drafts on a new
> pending review. The original review record stays on the PR timeline as an empty shell;
> GitHub does not allow deleting a submitted review. Apologies.

---

## Race-window protocol

A delete-and-recreate cycle has a few-second window where the pending review does not exist.
If the user is editing a draft comment in the browser during that window, their edit will
target a deleted review and fail.

Announce ONLY when the delete-and-recreate path is actually running, i.e. the existing pending
review has at least one comment. When a pending review has zero comments (Operation 1 Step
2a), skip the announce; there is no race window.

**Before** (when Step 2b runs):

> Syncing pending review now. Stay out of the PR UI until I confirm done.

**After** (once Step 2b POST succeeds):

> Sync done. OK to resume.

Plain wording, no prefix or emoji, consistent across invocations. Announce and proceed; do not
wait for acknowledgement, since the action was already approved.

---

## Technical notes

- **Multi-line comments.** REST's `/reviews/{id}/comments` returns `position` and
  `original_position` (end-of-span only) for pending comments; it does NOT return `startLine`
  or `line`. Use the GraphQL `node(id: ...)` query for round-trip fidelity.
- **CRLF handling.** GitHub may store bodies with `\r\n` after browser edits. Preserve what
  the server returns verbatim; do not normalize line endings.
- **Accumulator file.** `/tmp/pr-review-batching-<pr-number>.json`. Clean up on POST success;
  preserve on failure. `/tmp` on macOS does not reliably auto-clean, so explicit cleanup
  matters.
- **Empty review shell.** Once a review has state `COMMENTED`, `APPROVED`, or
  `CHANGES_REQUESTED`, the review record itself cannot be deleted via the API. Its inline
  comments can be. Surface this honestly in incident response.
- **Side field.** Default to `RIGHT` (changed file). `LEFT` refers to the base file
  pre-change and is rare for draft review comments.
- **`gh pr review` is disallowed in this skill.** Its flags (`--comment`, `--approve`,
  `--request-changes`) all set a non-`PENDING` event. Always use `gh api .../reviews` without
  `event` instead.

---

## Interaction with `pr-review`

`skills/pr-review/SKILL.md` Step 9 ends with: "Want me to draft these as pending-review
comments on the PR?" On confirmation it invokes this skill with the list of draft comments.
`pr-review` never calls `gh pr review` or sets `event=` directly; that decision lives here.

---

## Out of scope

- Pre-submit linting of draft bodies.
- Standalone "sync from server" without an append.
- Full CRUD on draft comments (PATCH is explicitly forbidden).
- Cross-session persistence of the accumulator; the server is the source of truth.
- Browser-only fallback when `gh` CLI is unavailable.
