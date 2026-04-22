---
name: pr-review
user-invocable: true
description: >
  AI-assisted GitHub PR review that produces concise, copy-paste-ready draft comments with line
  references and code suggestions. Cross-checks prior bot-generated reviews (Copilot, CodeRabbit,
  Codex, Sourcery, Gemini Code Assist, etc.) including resolved threads, and surfaces silent
  dismissals where bot-flagged code was resolved without change. Use this skill whenever the user
  shares a GitHub PR URL and wants a code review, second-set-of-eyes analysis, or help
  understanding a PR before approving. Trigger phrases include: "review this PR", "look at this
  PR", "give me feedback on this PR", "help me review", "PR review", "check this pull request",
  "review with bots", "check bot feedback", "I want to approve but need to understand", "draft
  review comments", or any message containing a github.com/*/pull/* URL.
---

# PR Review

You are acting as a thorough but concise code reviewer. Your job is to read a PR with fresh eyes,
identify real concerns worth flagging, and produce draft comments the user can paste directly into
GitHub. Don't manufacture issues — an empty section is better than a weak comment.

---

## Step 1: Determine the mode

Read the user's framing before you fetch anything:

- **Review mode** (default): user wants bugs, concerns, and draft PR comments. Output: tiered
  comments with file/line refs and code suggestions.
- **Understand-to-approve mode**: user says something like "I want to approve but need to understand
  this" or "help me formulate a review." Output: plain-English explanation of the changes, a
  concise risk/impact summary, a verification checklist, and a suggested approval comment.

Both modes start with the same fetch + analysis steps. The output format differs.

---

## Step 2: Fetch the PR

Use the `gh` CLI as the primary method. If `gh` isn't available or authenticated, fall back to the
browser tool with the user's session.

```bash
# Metadata + description
gh pr view <URL> --json title,body,number,additions,deletions,headRefName,baseRefName,author,files,labels

# Full diff
gh pr diff <URL>
```

If the diff is large (>500 lines changed), skim the file list first and prioritize files by likely
impact: logic files > config/manifest files > test files > generated files. Fetch specific file
contents as needed for line-level analysis:

```bash
gh api repos/{owner}/{repo}/contents/{path}?ref={head_sha}
```

Always fetch the **latest** state of the PR — never assume a previous analysis is still current.

---

## Step 3: Scan repo context (optional but valuable)

Before reviewing, spend a moment on:

- `CONTRIBUTING.md` or `docs/contributing*` — coding conventions, PR norms
- Linter config files: `.eslintrc*`, `golangci.yml`, `.golangci.toml`, `biome.json`, `.stylelintrc*`,
  `rustfmt.toml`, `pyproject.toml` (ruff/black sections), etc.
- Patterns in files adjacent to the changed code — naming conventions, error handling style

**If a linter config is detected, suppress style/formatting nits entirely.** Only flag things the
linter won't catch.

---

## Step 4: Detect the PR type

Classify the PR based on the diff and description. This shapes which concerns you weight most
heavily:

| Type | Key signals |
|------|-------------|
| `feature` | New components, new API endpoints, new user-facing flows |
| `bugfix` | Targeted fix, references an issue or repro steps |
| `refactor` | Restructuring without behavior change |
| `api-change` | Modified public interfaces, exported types, wire formats, route signatures |
| `dependency` | Changes to package.json, go.mod, requirements.txt, Cargo.toml |
| `config/ci` | Workflow YAML, Dockerfile, provisioning files, env templates |
| `schema/migration` | DB schema files, migration scripts, serialized formats |
| `scaffolding/tooling` | Build config, ESLint/compiler upgrade, generated file churn |
| `mixed` | Multiple of the above |

State the detected type at the top of your output.

---

## Step 5: Review focus areas

### Always check (regardless of PR type)

1. **Public API / contract changes** — Any change to exported functions, prop types, REST routes,
   gRPC schemas, event payloads, or serialized types is a potential breaking change. Flag if:
   - There's no versioning or deprecation strategy
   - External callers (other repos, plugins, services) aren't clearly accounted for
   - A companion PR is required for the change to be safe, and there's no reference to it

2. **New dependencies** — For every new import or package entry:
   - Is it actually necessary, or can existing deps cover this?
   - Is it classified correctly? If the PR description calls it "test-only" but it's in
     `dependencies` (not `devDependencies`), flag the mismatch.
   - Any known CVEs, maintenance concerns, or license issues?

3. **Rollout / migration timing** — If the PR is part of a multi-repo change or depends on a
   companion PR being deployed first, identify the window where the deployed state is unsafe.
   Flag the specific condition that would cause breakage and suggest a guard.

4. **Missing error handling on new code paths** — Any new async operation, external call, or
   fallible operation without error handling or a reasonable fallback.

5. **Stale or inconsistent state** — Mutable state (local state, cache, badges, derived values)
   that isn't reset when the underlying data changes.

### By PR type

**`feature` / `bugfix`**
- Does the fix address the root cause, or just a symptom?
- Are new code paths covered by tests?
- Edge cases: empty/null inputs, concurrent access, large inputs, auth-gated paths

**`api-change`**
- Is this a breaking change? (removed fields, changed types, new required params)
- Is there a deprecation path or version bump?
- Are all in-repo callers updated? Are out-of-repo callers known?

**`dependency`**
- Runtime vs devDependency classification
- Semver range: is `^` or `~` appropriate, or should it be pinned?
- Resolution/override entries: are they documented and scoped correctly?

**`refactor`**
- Behavioral equivalence: is any logic subtly changed in the restructure?
- Are tests exercising the refactored paths still passing and meaningful (not just renamed)?

**`config/ci`**
- Secrets/tokens: least-privilege scope? Vault-sourced vs hardcoded?
- Gating logic: does the automation trigger only on the intended conditions?
- Rollback: is there a safe path back if the config change causes issues?

**`schema/migration`**
- Reversible? Can the migration be rolled back without data loss?
- Null handling: are existing rows with NULL values handled?
- Performance at scale: any index changes or full-table operations on large tables?

**`scaffolding/tooling`**
- Plugin-specific config drift: was anything lost when migrating to a new config format?
- Build/test/lint parity: does the new tooling produce the same output?

---

## Step 6: Cross-check prior bot reviews

Bots frequently leave review comments that get marked resolved without a corresponding code change. "Resolved" on GitHub requires no code change — anyone with write access can click it — so resolution is not evidence a concern was addressed.

Account for: Copilot, Codex, CodeRabbit, Sourcery, Gemini Code Assist, and anything else authored by a GitHub App. Fetch every thread regardless of resolution state:

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

Treat a comment as bot-authored if `author.__typename == "Bot"` or the login matches a known bot (e.g. `copilot-pull-request-reviewer[bot]`, `coderabbitai[bot]`).

For each bot comment (resolved or not):

- Restate the claim in one sentence
- Verify against the current diff — is the flagged code still present, unchanged?
- Note `isOutdated`: `true` means GitHub detected the referenced lines changed (suggestive of addressed); `false` + `isResolved=true` + code unchanged is the canonical silent-dismissal signature
- Categorize: **still valid**, **addressed by later commit**, **false positive**, **style-only (linter-configured → ignore)**
- Any *still-valid* concern that was resolved without a corresponding code change is a **silent dismissal** — promote it into your own 🔴 Bugs or 🟡 Warnings output with the thread URL as traceability

Preserve thread `id`, comment `id`, and comment `url` for linking findings back to GitHub and for any follow-up mutations (e.g. `resolveReviewThread`).

**Pagination caveat:** the query caps at 100 threads × 20 comments each. On very noisy PRs, paginate via `pageInfo { hasNextPage endCursor }` with `after:` cursors before trusting the coverage is complete.

If no bots have commented on the PR, note `No bot reviews present.` and move on — don't fabricate coverage.

### ID type caveat

The GraphQL query above returns **node IDs** (base64-encoded, e.g. `PRRC_kwDONPDiQc6585CE` for comments, `PRRT_kwDONPDiQc58mSmJ` for threads). REST endpoints for replying to comments require **numeric IDs**. Two options when addressing a thread:

1. **Stay in GraphQL for mutations**: use `addPullRequestReviewComment` with `inReplyTo: <comment_node_id>` and `resolveReviewThread` with `threadId: <thread_node_id>`. No ID translation needed.
2. **Fetch numeric IDs from REST** before replying:

   ```bash
   gh api repos/{owner}/{repo}/pulls/{pull_number}/comments \
     --jq '.[] | {id, body: .body[:60], user: .user.login}'
   ```

   Then use the numeric `id` in the reply endpoint below.

Option 1 is preferred when posting replies as part of a pending review (aligns with `pr-review-batching`). Option 2 is simpler for standalone thread replies outside a review.

### Replying to review threads (REST)

```bash
# Reply to a specific review comment thread
gh api repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies \
  -f body=':zap: <commit_hash>'
```

Note: the pull number is required in the path. The comment-level GET endpoint (`/pulls/comments/{id}`) omits it, but the reply POST does not; `/pulls/comments/{id}/replies` returns 404.

### Resolving threads after reply

After replying to bot review threads, resolve every thread that received a definitive reply (accepted or rejected). An open thread signals "still needs attention"; a replied-to rejection is definitively addressed and should be resolved too. Timing depends on how the reply was posted:

- **Direct reply** (REST `/pulls/{pull_number}/comments/{id}/replies`): reply is immediately published. Resolve right after posting.
- **Staged as pending review draft** (via `pr-review-batching`): reply is only visible to the author until the user submits the review. Do NOT resolve until after submission. Resolving before publication leaves other reviewers seeing a resolved thread with no visible rationale (worse than silent dismissal).

There is no technical guard; `resolveReviewThread` succeeds regardless of whether a reply exists or is published. The constraint is purely workflow correctness.

Use the GraphQL mutation with the thread's node ID:

```bash
gh api graphql -f query='mutation {
  resolveReviewThread(input: {threadId: "<PRRT_node_id>"}) {
    thread { isResolved }
  }
}'
```

Batch multiple resolutions into a single GraphQL call using aliases:

```bash
gh api graphql -f query='mutation {
  t1: resolveReviewThread(input: {threadId: "<id1>"}) { thread { isResolved } }
  t2: resolveReviewThread(input: {threadId: "<id2>"}) { thread { isResolved } }
}'
```

---

## Step 7: Before you write a comment, verify it

This is the most important discipline in the skill. Before flagging a concern:

1. **Confirm the concern exists in the current diff** — not a previous version.
2. **Check if it's already addressed elsewhere in the PR** (another file, a follow-up commit).
3. **Consider if the PR description explains it** — the author may have already acknowledged the
   limitation.
4. **Be willing to say "this looks fine"** — a review with no comments is a valid outcome.

If you're uncertain whether a concern is real, briefly state your reasoning so the user can
validate it. "I'm not certain this is an issue, but here's why it caught my eye" is honest and
useful.

---

## Step 8: Output format

### Review mode (default)

```
## Summary
<2–3 sentences: what the PR does and why. State the PR type.>

---

## Review

### 🔴 Bugs
<Actual defects: logic errors, null/panic risks, incorrect behavior. If none, write "None identified.">

### 🟡 Warnings
<Non-blocking concerns: API contract risks, stale state, missing error handling, dependency
classification issues, rollout edge cases. If none, write "None identified.">

### 💡 Suggestions
<Optional improvements. Omit this section entirely if nothing genuine to say.>

### 🤖 Bot review coverage

| Bot | File · Line | Status | Assessment |
|-----|-------------|--------|-----------|
| Copilot | [src/foo.ts:42](https://github.com/owner/repo/pull/123#discussion_r111) | Resolved, not outdated | Still valid — code unchanged. **Silent dismissal** — promoted into 🔴 Bugs above. |
| CodeRabbit | [src/bar.ts:10](https://github.com/owner/repo/pull/123#discussion_r222) | Open | Valid, matches current diff. Rolled into 🟡 Warnings above. |
| Codex | [src/baz.ts:88](https://github.com/owner/repo/pull/123#discussion_r333) | Resolved, outdated | Addressed by commit abc1234. No action. |

<If no bots have commented: write "No bot reviews present." and omit the table.>
```

Each comment inside a section uses this format:

```
**`path/to/file.ext` · L<N>–<N>**
One or two sentences stating the concern and why it matters.

```suggestion
// corrected or improved code here
```
```

- File path relative to repo root, line numbers from the **final file** (not diff offsets)
- Code suggestion blocks use GitHub's ` ```suggestion ` format — they should be directly applicable,
  not pseudocode
- Keep comments terse: assume the reader is a competent developer who will understand the
  implication without elaboration
- Group closely related concerns into one comment rather than splitting into noise

### Understand-to-approve mode

```
## What changed
<Plain-English explanation of the change, broken down by logical area if needed.>

## Risk / impact
<What could go wrong? Who or what is affected? Is this low/medium/high risk and why?>

## Before you approve — checklist
- [ ] <specific thing to verify>
- [ ] <specific thing to verify>

## Suggested approval comment
<Ready-to-paste approval comment.>
```

---

## Step 9: Offer to stage as drafts

After presenting the review, ask:

> Want me to draft these as pending-review comments on the PR? I'll stage them as drafts; you
> submit the review manually when you're ready.

If the user confirms, hand off to the `pr-review-batching` skill with the list of comments
(path, line / start_line, side / start_side, body per comment). That skill owns the
submission lifecycle: detecting an existing pending review, appending without clobbering
user-in-flight edits, and incident response if a review gets published by mistake.

**Do NOT call `gh pr review` or `gh api .../pulls/.../reviews` with an `event` field from this
skill.** Any `event=COMMENT | APPROVE | REQUEST_CHANGES` publishes the review immediately,
which violates the user's convention that they submit manually. See
`skills/pr-review-batching/SKILL.md` for the runbook.

If the user wants something other than a batched draft review (for example, a standalone
non-inline review comment, or an explicit approval), confirm the intent explicitly before
taking any action that changes PR state.

---

## Notes

- **Repos you may encounter** include Grafana plugin repos (`grafana-adaptivelogs-app`,
  `grafana-adaptiveprofiles-app`, `gex-plugins`). These are TypeScript/React frontends with Go
  backends, using `react-hook-form`, RTK Query / react-query, Grafana plugin SDK conventions, and
  `gh` CLI for CI.
- **Language-specific defaults**: For TypeScript/React, check prop contract changes and hook
  dependency arrays. For Go, check error wrapping patterns and goroutine safety. For YAML workflows,
  check token scopes and trigger conditions.
- **Multi-repo PRs**: Grafana plugin PRs often have companion PRs in `profiles-drilldown` or other
  repos. Look for references in the PR description and flag any unresolved cross-repo dependencies.
