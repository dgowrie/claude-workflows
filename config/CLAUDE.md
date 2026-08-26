# CLAUDE.md - Global Defaults

Personal defaults applied across all sessions and projects. Local `CLAUDE.md` files take precedence.

## Tone and Behavior

- Be extremely concise. Sacrifice formality and grammar (but not clarity or meaning) for concision.
- No flattery or compliments unless explicitly asked for judgment.
- When uncertain about intent or direction, ask. Keep asking until ambiguity is fully resolved.
- When a follow-up question is contingent on a prior answer, either make the questions truly independent, or include an explicit "N/A - depends on the above" option. Never force an answer to a question whose premise a sibling question might invalidate.
- Don't speculate as if stating fact. When uncertain, say so and frame hypotheses as hypotheses.
- **No em dashes (U+2014) anywhere, ever.** This is absolute and applies to *everything you author*, not just chat prose: code, code comments, commit messages, PR/review comment bodies, API payloads, JSON you write to disk, file content, and docs. Use a hyphen, comma, semicolon, or parentheses instead. A PreToolUse hook blocks the em dash (U+2014) along with the en dash (U+2013) and horizontal bar (U+2015) in Write/Edit/Bash content as a backstop, but the prohibition holds everywhere, including surfaces the hook can't reach (e.g. MCP tool payloads).

## Agentic Workflow

**Session start**: Orient to the project first - check lockfile, `.nvmrc`, build scripts to determine package manager and toolchain. Never assume `npm`.

Standard loop: **Plan -> Implement (red/green/refactor) -> Validate -> Commit**. Pause at each phase boundary. Within a phase, work autonomously unless you hit ambiguity or an uncovered decision point.

**Offload to subagents early.** If a task has 3+ independent subtasks, spawn subagents rather than working sequentially. Reserve the main thread for synthesis, decisions, and sequencing.

## PR Decomposition

- **Small, independently mergeable PRs** - one shippable unit per PR. Tests pass, no dead code, no partial features visible to users. Feature flags and foundational types are often independently mergeable first.
- **Sequential PRs to main** is the default. **Stacked PRs** only when changes are genuinely interdependent.

## Concurrent Workstreams

- **Genuinely independent units only.** No file-level overlap, no import dependencies. If B imports from A, they're sequential.
- **Shared prerequisites go first.** Types, config, feature flags needed by multiple workstreams land before parallel work begins.
- **Each workstream gets its own branch** (and git worktree for concurrent sessions).
- **Rename branch when scope changes.** Worktree directory name is immutable - flag the mismatch but don't try to fix it.
- **Before going AFK**: push all branches, open PRs (draft if needed), leave clear next-step notes.
- **Don't force concurrency.** If the dependency chain is linear, sequential is faster.

## Plan Mode

Four sections. Pause after each for feedback:

1. **Goal & scope** - what and why
2. **Implementation steps** - concrete, file-level changes
3. **Open questions & assumptions**
4. **Risks & alternatives** - rejected alternatives with brief reasoning

Keep plans extremely concise. No abstract design discussion unless explicitly working through tradeoffs.

When a meaningful implementation fork exists: summarize options concretely, state tradeoffs, recommend one, ask.

User may invoke `/grill-me` before implementation to stress-test the plan.

### Picking up an existing plan

Review thoroughly, compare against codebase, flag gaps/ambiguities/mismatches.

For each issue: describe with file/line references, present 2-3 options (including "do nothing"), evaluate effort/risk/impact, recommend one, ask before proceeding.

## Testing - Red/Green/Refactor TDD

1. **Red** - write test(s) first, confirm they fail before any implementation. A test passing before implementation is broken.
2. **Green** - implement only enough to pass.
3. **Refactor** - only when clear improvement exists; avoid refactor loops.

**Session start**: run existing test suite before making changes.

**Bug fixes**: regression test first (red), then fix (green). Applies to bugs from development, CI, or review feedback alike.

**Frontend test selectors**: prefer a11y/semantic queries (`getByRole`, `getByLabelText`, `getByText`) over `data-testid` whenever the target has an accessible handle - they test what users and assistive tech actually perceive and survive refactors better. Don't add new `data-testid`s, or query existing ones, when a semantic query works. Fall back to `data-testid` only for decorative or layout-only elements with no accessible role. Leave pre-existing testids in place (they may back e2e selectors); just don't query by them in new tests.

## Definition of Done

- **Validate before pushing.** Tests pass, typecheck clean, lint clean. Full suite before push, even for "low-risk" changes.
- **Lint clean means zero warnings in files we touched**, not just zero errors. Lint fixes go in their own discrete commit.
- **Non-code changes still require validation.** Use available tooling (actionlint, yamllint, schema checks) or review against specs.
- **No untracked shortcuts.** No cut corners without documented tradeoffs and follow-up plan.

## Code Style and Engineering

- **DRY** - flag repetition aggressively
- **Well-tested** - err toward more tests
- **Appropriately engineered** - avoid both hacky and over-abstracted
- **Edge cases** - handle more rather than fewer
- **Explicit over clever; readable over terse**
- Descriptive, complete-word names; minimize abbreviations
- Small, single-responsibility functions
- Comments explain **why**, not **what**. Only when: purpose is non-obvious, deviating from standard approach, documenting a gotcha that can't be eliminated via code/types.
- Future work: `// TODO: description (#issue)`. Always greppable `TODO` prefix.
- **Markdown tables:** spaces on both sides of every `|` separator (markdownlint MD060).

## Tool Permissions and Sandbox

- **Read-only: never prompt.** `git diff`, `gh pr view`, `grep`, `ls`, `cat`, version checks, etc.
- **Local dev toolchain: auto-approve.** Install, test, build, lint, typecheck. Zero friction.
- **Write/destructive/irreversible: ask first.** `git`/`gh` writes, file deletions, side-effecting API calls.
- Local `CLAUDE.md` may add project-specific permissions or restrictions.

### Sandbox Workaround (interim - remove when #25 is resolved)

Use `dangerouslyDisableSandbox: true` **only** for:

- **`gh` CLI commands** - corporate proxy TLS causes `x509: OSStatus -26276`
- **`git push`, `git fetch`, `git clone`** against `github.com` - sandbox blocks the 1Password SSH agent socket

Go straight to `dangerouslyDisableSandbox` for these; don't retry inside sandbox first. Do not use it for `curl`, arbitrary HTTP calls, or SSH to non-GitHub hosts without explicit permission.

## External API Calls

- **Probe once, then parallelize.** First call to an unfamiliar endpoint runs sequentially. Parallel tool calls auto-cancel on first failure, wasting siblings on the same error.
- **Prefer `gh api --jq` over piping to `jq`.** `--jq` applies only on success; piped `jq` masks API errors. For first probes, omit jq entirely.
- **GraphQL node IDs ≠ REST numeric IDs.** Don't interchange them. Stay in one API surface for read-mutate cycles.

## Git Conventions

- [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description`. Scope optional but preferred.
- **Subject: 72 chars max.** Priority: (1) clear (2) conventional format (3) length. Body also 72-char wrapped.
- **No `Co-Authored-By` trailers.** No "Generated with Claude Code" attribution. Anywhere.
- **Discrete commits per PR.** Map to logical units: config/types, tests, implementation, lint autofix.
- **Lint autofix: always its own commit.**
- **Formatter-touched lines you didn't author = separate commit.** After `make fmt` / `prettier --write` / any autofix, run `git diff` **before staging**. Any hunk on a line you did not edit is lint-only: stage it with `git add -p` into its own `style:`/lint commit. Never `git add <whole file>` a formatter-modified file blind - that is exactly how lint autofix leaks into a feature/docs commit.
- **Never commit to default branch.** Always feature branch. Ask to confirm if on default branch.
- **Start from fresh main.** Fetch, update, branch before new work.
- **Never amend with open PR.** Creates force-push, loses review context. Always new commit.
- **Amending unpushed commits is always fine.** No confirmation needed.
- **Sync open PRs via merge, not rebase.** `git merge origin/main` preserves review timeline. Only rebase if draft/unshared or explicitly requested.

## Post-Push: CI Watch and Bot Review Triage

After pushing to any PR (including drafts), run both concurrently:

**CI Watch:**
- Poll with `gh pr checks`. On failure: read logs (`gh run view --log-failed`), diagnose, fix, commit, push, resume watching. On success: briefly confirm green.
- **CI is authoritative** - local validation is necessary but not sufficient.

**Bot Review Triage** (Copilot, Codex, etc.):
- Evaluate automatically: read all comments, verify each claim, categorize (accept/reject/nuance), present concise recommendation per comment.
- Act only with explicit authorization. Batch trivial fixes into one commit. Flag non-trivial scope separately.

## PR Review Conventions

**Addressing feedback** (human and bot):
- Accepted: reply `:zap: <commit hash>` plus a brief change/rationale summary. No affirmation prefixes ("good catch", "fair point", "great point", etc.); state what changed and why, nothing else.
- Rejected: reply `:thought_balloon: <brief rationale>`.
- Batch trivial fixes; non-trivial gets its own commit.
- **Only resolve threads we authored.** Reviewer threads stay open so reviewers can see what was flagged and weigh in. For our threads: resolve after reply is published (if staged as pending, wait until review is submitted).
- Use `resolveReviewThread` GraphQL mutation; never `minimizeComment`.

**Posting reviews on my behalf:**
- Never post comments individually. Use pending review mechanism.
- Present batch for confirmation; I submit manually.

## Author Review Guidance

When asked, post review-guidance comments on our own PRs as a **single review submission**: walkthrough as review body, inline comments threaded below.

**Walkthrough** (review body):
- One-paragraph summary of what changed and why.
- Ordered file list in suggested reading order: file path, what changed, why that order.
- Call out what reviewers should skip (mechanical renames, generated code).

**Inline comments** (on specific diff lines):
- Prefix with :notebook: to distinguish from review feedback.
- Add for: dense logic, intentional tradeoffs, subtle constraints, anything where "why this way?" is predictable.
- Skip for: obvious changes, anything the walkthrough already covers.
- Flag risk. Keep to 1-2 sentences. If it needs more, the code needs a real comment.

**Mechanics:** Stage via pr-review-batching skill. Don't duplicate PR description or commit messages; reference them.
