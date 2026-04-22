# CLAUDE.md - Global Defaults

Personal defaults applied across all sessions and projects. Local `CLAUDE.md` files take precedence.

## Tone and Behavior

- Be extremely concise. Sacrifice formality and grammar (but not clarity or meaning) for concision. Short summaries over extended breakdowns.
- No flattery or compliments unless explicitly asked for judgment.
- When uncertain about intent or direction, ask. Keep asking until ambiguity is fully resolved - don't guess.
- **No em dashes anywhere.** Applies to chat output, PR comments, commit messages, code comments, documentation, everything. Use hyphens, commas, or semicolons.

## Agentic Workflow

**Session start**: Orient to the project first - check lockfile, `.nvmrc`, build scripts to determine package manager and toolchain. Never assume `npm`.

Standard loop: **Plan -> Implement -> Test -> Commit**. Pause at each phase boundary. Within a phase, work autonomously unless you hit ambiguity or an uncovered decision point.

## PR Decomposition

- **Small, independently mergeable PRs** - one shippable unit per PR. Tests pass, no dead code, no partial features visible to users. Feature flags and foundational types are often independently mergeable first.
- **Sequential PRs to main** is the default. Each merges independently; next PR starts from updated main.
- **Stacked PRs** only when changes are genuinely interdependent. Rebasing overhead isn't worth it when work can be sequential.

## Concurrent Workstreams

When preparing parallel work (multiple Claude sessions, AFK periods, handoffs):

- **Genuinely independent units only.** No file-level overlap, no import dependencies, each mergeable alone. If B imports from A, they're sequential.
- **Shared prerequisites go first.** Types, config, feature flags needed by multiple workstreams land in a small PR before parallel work begins.
- **Each workstream gets its own branch** (and git worktree for concurrent sessions). Never two workstreams on one branch.
- **Rename branch when scope changes.** Worktree directory name is immutable - flag the mismatch but don't try to fix it.
- **Before going AFK**: push all branches, open PRs (draft if needed), leave clear next-step notes.
- **Don't force concurrency.** If the dependency chain is linear, sequential is faster.

## Plan Mode

Four sections. Pause after each for feedback:

1. **Goal & scope** - what and why
2. **Implementation steps** - concrete, file-level changes
3. **Open questions & assumptions** - unresolved questions; unconfirmed assumptions
4. **Risks & alternatives** - uncertainty, rejected alternatives with brief reasoning

Keep plans extremely concise. Sacrifice grammar for concision. No abstract design discussion unless explicitly working through tradeoffs.

When a meaningful implementation fork exists: summarize options concretely, state tradeoffs, give opinionated recommendation, ask for input.

User may invoke `/grill-me` before implementation to stress-test the plan.

### Picking up an existing plan

Before implementing against an existing plan:

- Review thoroughly. Flag gaps, ambiguities, inconsistencies.
- Compare against codebase. Flag mismatches.

For each issue found: describe concretely with file/line references, present 2-3 options (including "do nothing"), evaluate effort/risk/impact, recommend one, ask before proceeding.

## Testing - Red/Green/Refactor TDD

Follow classic TDD universally:

1. **Red** - write test(s) first, confirm they fail before any implementation. A test passing before implementation is broken.
2. **Green** - implement only enough to pass.
3. **Refactor** - investigate improvements to both implementation and test code. Only when clear improvement exists; avoid refactor loops.

**Session start**: run existing test suite before making changes. Establishes baseline and catches regressions.

**Bug fixes**: regression test first (red), then fix (green). Applies to bugs from development, CI, or review feedback alike.

## Definition of Done

- **Validate before pushing.** Tests pass, typecheck clean, lint clean. Full suite before push. Applies even for "low-risk" changes.
- **Non-code changes still require validation.** CI workflows, config - use available tooling (actionlint, yamllint, schema checks) or review against specs.
- **No untracked shortcuts.** No cut corners without documented tradeoffs and follow-up plan.

## Engineering Preferences

- **DRY** - flag repetition aggressively
- **Well-tested** - err toward more tests
- **Appropriately engineered** - avoid both hacky and over-abstracted
- **Edge cases** - handle more rather than fewer
- **Explicit over clever**
- **Readable and maintainable** over terse

## Code Style

- Descriptive, complete-word names; minimize abbreviations
- Small, single-responsibility functions
- Comments only when: purpose is non-obvious, deviating from standard approach, documenting a gotcha that can't be eliminated via code/types. Never restate what names already say. Explain **why**, not **what**.
- Future work comments: `// TODO: description (#issue)`. Always greppable `TODO` prefix - no freeform "see #123".
- **Markdown tables:** spaces on both sides of every `|` separator. Enforced by markdownlint MD060.

## Self-Correction Loop

On correction (user or self-caught): propose `CLAUDE.md` update **immediately, before continuing the task**.

- **Trigger**: user correction; or Claude catches a self-correction worth generalizing
- **Scope**: substantive mistakes, violated preferences, meaningful tone/style findings
- **Target**: global `CLAUDE.md` if broadly applicable; most local `CLAUDE.md` otherwise
- **Process**: (1) stop task (2) propose rule + reasoning (3) apply on confirmation (4) resume

## Memory Hygiene

- **Index descriptions: specific and filterable** - name feature, issue number, or domain. No vague descriptions.
- **Individual files under 1KB.** Over 2KB belongs in a plan, repo doc, or code comment.
- **Check for existing memory before writing new.** Fewer well-scoped > many granular.
- **Delete shipped/resolved/obsolete memories.** Remove file and MEMORY.md entry.
- **Project context -> memory. Global rules -> CLAUDE.md.** Promote feedback memories useful across 2+ sessions.

## Tool Permissions

- **Read-only: never prompt.** Any command that only reads state (`git diff`, `gh pr view`, `grep`, `ls`, `cat`, version checks, etc.). All contexts.
- **Local dev toolchain: auto-approve.** Install, test, build, lint, typecheck commands. Treat like Read tool calls - zero friction, zero ceremony. All contexts.
- **Write/destructive/irreversible: ask first.** `git`/`gh` writes, file deletions, state-modifying commands, side-effecting API calls.
- Local `CLAUDE.md` may add project-specific permissions or restrictions.

## External API Calls

- **Probe once, then parallelize.** First call to an unfamiliar endpoint (or new parameter shape) runs sequentially. Only parallelize siblings after that probe succeeds. Parallel tool calls auto-cancel on first failure, wasting all siblings on the same systematic error (wrong path, wrong ID type, wrong auth).
- **Prefer `gh api --jq '<filter>'` over `gh api ... | jq '<filter>'`.** The `--jq` flag applies only on success; API errors print raw to stderr, preserving the real failure. External `jq` processes error HTML identically to JSON, producing parse errors that mask the underlying issue. For first probes, omit jq entirely to see the raw response.
- **GraphQL node IDs ≠ REST numeric IDs.** Base64 node IDs (e.g. `PRRC_kwDO...`) returned by GraphQL are not interchangeable with numeric IDs required by REST endpoints. Translate deliberately, or stay in one API surface for the full read-mutate cycle.

## Git Conventions

- [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description`. Scope optional but preferred.
- **Subject: 72 chars max.** Priority: (1) clear (2) conventional format (3) length. Body also 72-char wrapped.
- **No `Co-Authored-By` trailers.** No "Generated with Claude Code" attribution.
- **Discrete commits per PR.** Map to logical units: config/types, tests, implementation, lint autofix.
- **Lint autofix: always its own commit.**
- **Never commit to default branch.** Always feature branch. Ask to confirm if on default branch.
- **Start from fresh main.** Fetch, update, branch before new work.
- **Never amend with open PR.** Creates force-push, loses review context. Always new commit.

## CI Watch

After pushing to any PR (including drafts), proactively monitor CI:

- **Poll** with `gh pr checks`. Don't wait for user to report failures.
- **On failure**: read logs (`gh run view --log-failed`), diagnose, fix, commit, push, resume watching.
- **On success**: briefly confirm green.
- **CI is authoritative** - local validation is necessary but not sufficient.
- **Run CI watch and bot review triage concurrently** after each push.

## Bot PR Review Triage

After pushing a new PR, watch for bot review comments (Copilot, Codex, etc.).

**Evaluate automatically:** read all comments, verify each claim, categorize (accept/reject/nuance), present concise recommendation per comment.

**Act only with explicit authorization:** batch trivial fixes into one commit, reply per review feedback conventions below. Flag non-trivial scope separately.

## PR Review Conventions

**Addressing feedback** (human and bot):
- Accepted: reply `:zap: <commit hash>`, minimal commentary.
- Rejected: reply with brief rationale.
- Batch trivial fixes; non-trivial gets its own commit.
- **Resolve every thread with a definitive reply, after that reply is published.** Applies to both accepted and rejected. If replies are staged as pending review drafts, wait until the user submits the review before resolving; resolving before publication leaves other reviewers seeing a resolved thread with no visible rationale (invisible dismissal). An open thread signals "still needs attention"; a resolved thread with no visible reply signals "invisible dismissal."
- Use `resolveReviewThread` GraphQL mutation; never `minimizeComment`.

**Posting reviews on my behalf:**
- Never post comments individually. Use pending review mechanism.
- Present batch for confirmation; I submit manually to control review event type.
