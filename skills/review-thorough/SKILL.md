---
name: review-thorough
user-invocable: true
description: >
  Wrapper around the built-in /review command that additionally fetches and evaluates every
  bot-generated review on the PR — including threads marked resolved. Use when you want the
  standard /review flow plus assurance that prior bot feedback hasn't been silently dismissed.
  Trigger phrases: "thorough review", "review with bots", "review-thorough", "review this PR
  including resolved bot comments".
---

# Thorough PR Review

Perform the built-in `/review` flow in full, then extend it with explicit bot-review coverage.
"Resolved" on GitHub requires no code change — anyone with write access can click it — so resolution is not evidence a concern was addressed.

---

## Step 1: Run the built-in review

Invoke the built-in `review` command via the Skill tool (`skill="review"`) — the same mechanism Claude Code uses when a user types `/review`. Let it run in full and capture its complete output (summary, bugs, warnings, suggestions). Do not paraphrase, skip, or abbreviate.

## Step 2: Enumerate all bot review threads — resolved or not

Bots to account for include Copilot, Codex, CodeRabbit, Sourcery, Gemini Code Assist, and anything else authored by a GitHub App. Fetch every thread including its resolution state:

```bash
gh api graphql -f query='
  query($owner:String!, $repo:String!, $number:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$number) {
        reviewThreads(first:100) {
          nodes {
            id
            isResolved
            isOutdated
            path
            line
            originalLine
            comments(first:20) {
              nodes {
                id
                url
                author { login __typename }
                body
                createdAt
                line
                originalLine
              }
            }
          }
        }
      }
    }
  }' -f owner=<owner> -f repo=<repo> -F number=<num>
```

Preserve thread `id`, comment `id`, and comment `url` — they're the pointers used for linking findings back to GitHub and for any follow-up mutations (e.g. `resolveReviewThread`). Keep `isOutdated` alongside `isResolved`: GitHub flips `isOutdated=true` automatically when the referenced lines change, which is evidence — unlike resolution — that the underlying code moved.

Treat a comment as bot-authored if `author.__typename == "Bot"` or the login matches a known bot (e.g. `copilot-pull-request-reviewer[bot]`, `coderabbitai[bot]`).

## Step 3: Evaluate each bot comment against the current diff

For each bot comment (resolved or not):

- Restate the claim in one sentence
- Verify against the current diff — is the flagged code still present, unchanged?
- Note `isOutdated`: `true` means GitHub detected the referenced lines changed (suggestive of addressed); `false` + `isResolved=true` + code unchanged is the canonical silent-dismissal signature
- Categorize: **still valid**, **addressed by later commit**, **false positive**, **style-only (linter-configured → ignore)**
- Any *still-valid* concern that was resolved without a corresponding code change is a **silent dismissal** — surface it explicitly, with the thread URL

## Step 4: Output

Append a new section to the standard `/review` output:

```
### 🤖 Bot review coverage

| Bot | File · Line | Status | Assessment |
|-----|-------------|--------|-----------|
| Copilot | [src/foo.ts:42](https://github.com/owner/repo/pull/123#discussion_r111) | Resolved, not outdated | Still valid — code unchanged. **Silent dismissal** — surfacing. |
| CodeRabbit | [src/bar.ts:10](https://github.com/owner/repo/pull/123#discussion_r222) | Open | Valid, matches current diff. Rolled into 🟡 Warnings above. |
| Codex | [src/baz.ts:88](https://github.com/owner/repo/pull/123#discussion_r333) | Resolved, outdated | Addressed by commit abc1234. No action. |
```

Each file·line cell links to the bot comment URL (from `comments.nodes.url`) so silent-dismissal findings are traceable back to the original thread. Promote silent-dismissal items into the main `🔴 Bugs` or `🟡 Warnings` sections with full file/line context, the thread URL, and a draft comment — same format as the built-in review.

If no bots have commented on the PR, write `No bot reviews present.` and move on. Don't fabricate coverage.

---

## Limitations

The GraphQL query fetches up to 100 threads × 20 comments each. Very noisy PRs may exceed either ceiling — if counts approach those limits, paginate via the `pageInfo { hasNextPage endCursor }` fields and loop with `after:` cursors before trusting the coverage is complete.
