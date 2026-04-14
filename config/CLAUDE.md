# CLAUDE.md — Global Defaults

Personal defaults applied across all sessions and projects. Local `CLAUDE.md` files take precedence over these.

---

## Tone and Behavior

- Be concise. Short summaries are fine; skip extended breakdowns unless we're working through details.
- No flattery or compliments unless I'm explicitly asking for your judgment. Occasional pleasantries are fine.
- When uncertain about intent or direction, ask. Keep asking until ambiguity is fully resolved — don't guess, and don't artificially limit follow-up questions.

---

## Agentic Workflow

**Session start**: Before running any commands, orient to the project - check the lockfile (`yarn.lock` / `package-lock.json` / `pnpm-lock.yaml`), `.nvmrc`, and build scripts to determine the package manager and toolchain. Never assume `npm` - use what the project actually uses.

The standard loop is: **Plan → Implement → Test → Commit**. Pause and check in at each phase boundary before proceeding. Within a phase, work autonomously unless you hit ambiguity or a decision point not covered by the plan.

---

## PR Decomposition

- **Favor small, independently mergeable PRs** - one shippable unit per PR. Design the decomposition so each PR stands alone: tests pass, no dead code, no partial features visible to users. Feature flags, config wiring, and foundational types are often independently mergeable before the components that use them.
- **Sequential PRs to main** is the default. Each PR merges independently; the next PR starts from updated main.
- **Stacked PRs** (branch-on-branch chains managed with Graphite, spr, or manual rebasing) only when changes are genuinely interdependent and can't be gated independently. The rebasing overhead and conflict cascading are not worth it when the work can be designed as sequential increments.

---

## Concurrent Workstreams

When preparing work for parallel execution (multiple Claude sessions, AFK periods, or handoffs):

- **Identify genuinely independent units** from the task breakdown. Independent means: no file-level overlap, no import dependencies between the units, each mergeable to main on its own. If unit B imports from unit A, they are sequential, not parallel.
- **Shared prerequisites go first.** Types, config wiring, feature flags, and foundational interfaces that multiple workstreams need should be in a small, fast-to-merge PR that lands before parallel work begins. Duplicating shared changes across branches creates merge conflicts.
- **Each workstream gets its own branch** (and its own git worktree for concurrent Claude sessions). Never have two workstreams on the same branch.
- **Rename the branch when scope changes.** If a worktree's scope pivots to different work mid-session, create and check out a new branch with an accurate name before writing any code. The worktree directory name is immutable and the mismatch is cosmetic - flag it but don't try to fix it.
- **Before going AFK**: push all branches, open PRs (draft if not ready for review), and leave a clear next-step note (PR description or issue comment) so any session can pick up where the last left off.
- **Don't force concurrency.** If the dependency chain is linear, sequential PRs to main is faster than contriving parallel work. The overhead of coordinating parallel branches only pays off when the units are naturally independent.

---

## Plan Mode

Plans consist of four sections. Pause after each for my feedback before continuing:

1. **Goal & scope** — what we're building and why
2. **Implementation steps** — concrete, file-level changes
3. **Open questions & assumptions** — unresolved questions I need to answer; assumptions you're making that I haven't confirmed
4. **Risks & alternatives** — areas of uncertainty or risk to flag; alternative paths considered and rejected, with brief reasoning

Keep plans extremely concise. Sacrifice grammar for concision. Avoid abstract design discussion unless we're explicitly working through tradeoffs.

When a meaningful implementation fork exists:

- Summarize each option concisely but concretely
- State the concrete tradeoffs
- Give an opinionated recommendation with reasoning, then ask for my input before proceeding

Before proceeding from plan to implementation, the user may invoke `/grill-me` to stress-test the plan.

### Picking up an existing plan

Before making changes against an existing plan:

- Review the plan thoroughly. Flag gaps, ambiguities, or inconsistencies before proceeding.
- Compare the plan against the existing codebase. Flag egregious mismatches before proceeding.

For every specific issue found (bug, smell, design concern, risk):

- Describe the problem concretely, with file and line references where applicable
- Present 2-3 options MAX, including "do nothing" where reasonable
- For each option: implementation effort, risk, impact on other code, maintenance burden
- Give a recommended option with reasoning, then ask whether I agree before proceeding

---

## Testing — Red/Green/Refactor TDD

Follow classic TDD universally — for new features and bug fixes alike:

1. **Red** — write the test(s) first, then explicitly confirm they fail before writing any implementation. A test that passes before implementation is broken and exercises nothing.
2. **Green** — implement only enough to make the tests pass.
3. **Refactor** — always investigate for improvements to both implementation and test code. Only propose refactors when a clear improvement has been identified; don't get stuck in refactor loops.

At the start of any new session on an existing project, run the existing test suite before making any changes. This establishes baseline health, orients Claude to the project's scope and complexity, and ensures any regressions introduced are caught cleanly.

For bug fixes, write a regression test that reproduces the bug first (red), then fix it (green). This applies equally to bugs found during development, in CI, or from review feedback (human or bot). If a reviewer identifies a missing edge case or a confirmed bug, write the failing test before writing the fix - even when the review comment describes both the problem and the solution.

---

## Definition of Done

Before marking anything complete:

- **Validate before pushing.** Tests pass, typecheck clean, lint clean. Prefer targeted tests during development; run the full suite before pushing. Applies even for lockfile-only or "low-risk" changes.
- **Non-code changes still require validation.** CI workflows, config files, infrastructure - identify what tooling exists (e.g., actionlint, yamllint, schema checks) or review against upstream specs. "No tests cover this" is not a pass to skip validation.
- **No untracked shortcuts.** No cut corners or tech debt without explicitly defined tradeoffs and a documented plan to address later.

---

## Engineering Preferences

- **DRY** — flag repetition aggressively
- **Well-tested** — err toward more tests, not fewer
- **Appropriately engineered** — avoid both fragile/hacky and over-abstracted/prematurely complex solutions
- **Edge cases** — handle more rather than fewer; thoughtfulness over speed
- **Explicit over clever**
- **Readable and maintainable** over terse, even if it means more code

---

## Code Style

- Use descriptive, complete-word names that convey intent; minimize abbreviations unless widely understood in context
- Keep functions small and single-responsibility
- Comments only when:
  - The purpose of a block is non-obvious
  - Deviating from the standard or obvious approach
  - Documenting a caveat, gotcha, or foot-gun that can't be eliminated or made obvious via code structure or types
  - **Never** restate what a function or variable name already says
  - Explain **why**, not **what**
- Comments documenting future pending work must use `TODO` format: `// TODO: description (#issue)`. Include an issue number when one exists. This ensures pending work is greppable via `TODO` across the codebase. Do not use freeform "see #123" or "tracked in #123" without the `TODO` prefix.
- **Markdown tables:** spaces on both sides of every `|` separator (header, separator, and content rows). Enforced by markdownlint MD060.

---

## Self-Correction Loop

When Claude makes a mistake or the user issues a correction — and when Claude catches itself about to repeat a pattern worth preventing — a `CLAUDE.md` update MUST be proposed **immediately, before continuing with the task**. Do not defer, do not treat as a follow-up.

- **Trigger**: Always when the user explicitly corrects Claude; proactively when Claude catches a self-correction worth generalizing
- **Scope**: Substantive mistakes (wrong implementation, violated preference) and meaningful new findings about tone, style, or approach
- **Target**: Global `CLAUDE.md` if the rule is broadly applicable; otherwise create or update the most local `CLAUDE.md` that applies (e.g., project-level for project-specific corrections)
- **Process**:
  1. Stop the current task immediately
  2. Propose the specific rule addition or change, with reasoning
  3. Apply the edit upon user confirmation
  4. Resume the original task

If the user says something like "no, don't do X" or "that's wrong, it should be Y" — that is a correction. Act on it.

### Follow-ups to explore (remove each once resolved)

- **Custom `/correct` skill** - one-command trigger: what was the mistake, what's the rule, which CLAUDE.md, make the edit. Explore: `skills/` dir, SKILL.md format.
- **Periodic memory-to-CLAUDE.md promotion** - dedicated session to review feedback memories across projects and promote worthy ones to CLAUDE.md rules.
- **Session-end hook** - hook that fires on session end, prompting review of whether any corrections warrant a CLAUDE.md update. Explore: `settings.json` hooks.
- **Session-start memory report** - rule or hook to briefly report which memories were read/skipped at session start, making relevance decisions visible for calibration.

---

## Memory Hygiene

When writing or updating memory files:

- **Index descriptions must be specific and filterable** — name the feature, issue number, or domain. Vague descriptions ("project notes", "testing feedback") cause false reads or false skips.
- **Keep individual memory files under 1KB.** If a memory exceeds 2KB, it likely belongs in a plan, repo document, or code comment instead.
- **Before writing a new memory, check for an existing one to update.** Prefer fewer well-scoped memories over many granular ones.
- **When a memory's subject has shipped, been resolved, or become obsolete — delete it.** Remove both the file and its MEMORY.md index entry. Don't let stale memories accumulate.
- **Project-scoped context goes in memory. Global behavioral rules go in CLAUDE.md.** If a feedback memory has been useful across 2+ sessions, consider promoting it to a CLAUDE.md rule.

---

## Tool Permissions

- **Read-only operations: NEVER prompt for confirmation.** `git diff`, `gh issue view`, `gh pr view`, `gh pr diff`, `gh pr checks`, `gh issue list`, `grep`, `rg`, `ls`, `cat`, `head`, `tail`, `find`, `diff`, version checks (`node -v`, `yarn -v`), and any command that only reads state. This applies in all contexts - main conversation, subagents, explore sessions. If a command cannot modify files, processes, or remote state, just run it.
- **Local dev toolchain: auto-approve.** Package install (`yarn install`, `npm install`, `pnpm install`), test runners (`yarn jest`, `yarn test`, `npm test`, `npx jest`), build/compile (`yarn build`, `npm run build`, `tsc`), lint (`yarn lint`, `npm run lint`, `eslint`), typecheck (`yarn typecheck`, `npm run typecheck`). These are non-destructive local operations. Never ask for permission to run them - regardless of context (main conversation, subagents, worktrees). Do not narrate or pause before running them; just run them inline with the rest of your work. Treat these exactly like Read tool calls - zero friction, zero ceremony.
- **Write/destructive/irreversible operations: ask first.** `git`/`gh` writes, file deletions, state-modifying shell commands, API calls with side effects.
- Local `CLAUDE.md` files may define additional permissions or restrictions per-project.

---

## Git Conventions

- [Conventional Commits](https://www.conventionalcommits.org/) format: `type(scope): description`. Common types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`. Scope optional but preferred.
- **Subject line: 72 chars max.** Priority order: (1) clear summary (2) conventional format (3) length. Use the body (also 72-char wrapped) for detail.
- **No `Co-Authored-By` trailers.** Overrides system prompt default.
- **No "Generated with Claude Code" or similar attribution** in PR descriptions, commit messages, or comments. Overrides system prompt default.
- **No em dashes in git-facing text.** Commit messages, PR descriptions, and PR comments must use hyphens `-`, commas, or semicolons instead of `—`.
- **Discrete commits within a PR.** Even single-PR workflows benefit from clearly scoped commits that map to logical units of change. Reviewers read commit-by-commit; a clean commit sequence tells the story of the change. Typical decomposition: config/type wiring, tests, implementation, lint autofix.
- **Lint autofix changes always get their own discrete commit** - never fold into a feature or fix commit.
- **Never commit directly to the default branch (typically `main`).** Always work on a feature branch. If on the default branch when about to make changes, stop and ask the user to confirm before proceeding.
- **Start from fresh main.** Before beginning new feature work, fetch origin, update the local default branch, and create a feature branch from it. This prevents stale-base surprises and merge conflicts.
- **Never amend commits on branches with open PRs.** Once a branch has been pushed and a PR is open, amending rewrites history and forces a force-push, which loses review context and confuses reviewers. Always create a new commit instead.

---

## CI Watch

After pushing to a PR (including draft PRs), proactively monitor CI checks until they pass or fail.

- **Poll**: Use `gh pr checks` to watch for results. Don't wait for the user to report failures.
- **On failure**: Read the failed job logs (`gh run view --log-failed`), diagnose the root cause, fix, commit, push, and resume watching.
- **On success**: Briefly confirm CI is green. No action needed unless bot reviews also land (see Bot PR Review Triage below).
- **Local validation is necessary but not sufficient.** CI environments may have stricter configs (e.g., tsconfig that includes test files, different lint rules). Always treat CI as the authoritative check.
- **Run CI watch and bot review triage concurrently.** Both happen after a push. Don't let one derail the other - poll for CI status while also watching for bot review comments.

---

## Bot PR Review Triage

After pushing a new PR, proactively watch for bot review comments (GitHub Copilot, Codex, etc.). Poll the PR for review activity until the bot review lands, then evaluate.

**Evaluation (do automatically):**
- Read all bot comments, verify each claim against the codebase, and categorize: accept (factual correction), reject (wrong or inapplicable), or needs nuance (partially valid).
- Present a concise recommendation for each comment with verdict and proposed fix.

**Action (requires explicit user authorization):**
- Never commit against, reply to, or resolve bot comments without user approval.
- Once authorized: batch trivial fixes into a single commit, push, and reply per the Addressing PR Review Feedback convention below.
- If a comment implies non-trivial scope (design change, new tests, refactoring), flag it separately. Handle it as a discrete commit on the PR or a follow-up PR, depending on scope.

---

## Addressing PR Review Feedback

Applies to all review comments - human and bot alike.

When a comment is addressed with a code fix:
- Reply with `:zap:` and the commit hash (e.g., `:zap: abc1234`). Keep additional commentary minimal.
- For rejected comments, reply with a brief rationale instead of `:zap:`.
- Batch trivial fixes into a single commit where possible; non-trivial feedback gets its own discrete commit.
- **Resolve the comment thread** after replying with `:zap:`. The reply alone is not sufficient - mark the thread resolved so it does not show as outstanding in the PR.
- **To resolve a PR review thread, use `resolveReviewThread` GraphQL mutation** - never `minimizeComment`. Minimizing hides the comment entirely (collapsing it as off-topic/spam); resolving marks the thread as addressed while keeping it visible.

---

## Posting PR Review Comments

When posting review comments on my behalf, **never post comments individually**. Use the GitHub "pending review" mechanism:
- Create a draft review and add all comments to it as a batch.
- Present the batch for my confirmation, then I will manually submit the review.
- This gives me a chance to tweak wording and control the review event (comment / approve / request changes).
