# GitHub API Mechanics

Non-obvious GitHub REST/GraphQL details that bite when scripting PRs and issues with `gh`. Each cost a failed call the first time; probe the endpoint per the "probe once" rule rather than guessing.

## Review-thread reply and resolve

- **Reply field is `in_reply_to`, not `in_reply_to_id`** on `POST /pulls/{n}/comments`. Probe the endpoint before guessing the field name.
- **`resolveReviewThread` needs a `PRRT_` ID, not `PRRC_`.** A review comment's `node_id` is `PRRC_` (PullRequestReviewComment), but the mutation requires a `PRRT_` (PullRequestReviewThread) ID. The comment node id looks like it should work and does not. Always query `pullRequest.reviewThreads` to get the thread id rather than reusing the comment node id.

(Sits alongside the general "GraphQL node IDs are not REST numeric IDs" and "use `resolveReviewThread`, never `minimizeComment`" notes in CLAUDE.md.)

## Sub-issues: set the native parent relationship

When creating a sub-issue, set GitHub's native parent/child relationship, not just a body text reference. The user expects the structural link to show in GitHub's UI.

- After creating the child, call the `addSubIssue` GraphQL mutation: `addSubIssue(input: { issueId: "<parent node id>", subIssueId: "<child node id>" })`, using the node ids of both issues.

## Requesting Copilot as a PR reviewer

`gh pr create --reviewer @copilot` and `gh pr edit --add-reviewer @copilot` do NOT add Copilot; they silently no-op or error ("Could not add requested reviewers"), leaving only CODEOWNERS teams on the PR. Copilot is a bot account (`copilot-pull-request-reviewer[bot]`) and `gh`'s `--reviewer` resolution does not map `@copilot` to it.

- **Request it via REST after the PR exists:** `gh api -X POST repos/<owner>/<repo>/pulls/<n>/requested_reviewers -f "reviewers[]=copilot-pull-request-reviewer[bot]"`. When it works the response shows reviewer login `Copilot`.
- **Always verify it stuck:** `gh pr view <n> --json reviewRequests` (or `gh api .../requested_reviewers`). Do not assume the POST landed.
- **200-but-empty means per-repo gating, not a syntax error.** The POST can return HTTP 200 yet drop the bot, leaving `requested_reviewers` empty with no 422. That means Copilot review is not enabled/assignable for that repo (or org policy blocks it). GraphQL is no fallback: `suggestedActors` exposes only `CAN_BE_ASSIGNED`/`CAN_BE_AUTHOR` (no reviewer capability), and Copilot is absent from the assignable list. When the 200-but-empty pattern shows: stop after 2 attempts, then add Copilot from the PR's browser Reviewers menu or accept it is not enabled for that repo. Assignability is per-repo, so it can stick on one repo and silently drop on another.
