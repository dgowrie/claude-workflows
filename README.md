# claude-workflows

A personal knowledge base for how I work with Claude Code — the learnings, patterns, and tools that accumulate through daily use but have no natural home.

Claude Code's built-in persistence (memory, plans) is useful but fragile: memories are project-scoped and best-effort, plans don't resurface automatically, and corrections made in one session often don't survive to the next. This repo is the durable layer on top — a place to capture what I've learned, share it with peers, and build on it over time.

## Structure

```
config/        Global CLAUDE.md and rules, symlinked into ~/.claude/
internals/     How Claude Code works under the hood
workflows/     Patterns and practices for effective use
explorations/  Session notes and behavioral findings
skills/        Skill drafts before deploying to ~/.claude/skills/
agents/        Subagent definitions, symlinked into ~/.claude/agents/
```

## Contents

### Internals

- [Claude Code Internals — Cheat Sheet](internals/claude-code-internals-cheatsheet.md)
- [Claude Code Internals — Presentation](internals/claude-code-internals-presentation.html) (Reveal.js, open in browser)
- [Memory & Context Management](internals/memory-context-management.md) — how memory impacts token usage, two-tier loading, scaling guidelines
- [Sandbox Mode Evaluation](internals/sandbox-mode-evaluation.md) — sandbox restrictions, auto-allow boundaries, risk assessment, native sandbox vs Docker

### Workflows

- [Skill Management](workflows/skill-management.md) — three-tier sync architecture, creation flows, launchd watcher

### Explorations

- [Milestone Ralph vs AIHero Ralph](explorations/milestone-ralph-vs-aihero.md) — capability comparison and roadmap implications for the milestone-driven Ralph skills

### Skills

Skills in this repo are symlinked into `~/.claude/skills/`, making them globally available across all projects. Claude Code only loads skills from `~/.claude/skills/`, so without the symlink a skill defined here would only be accessible when working in this repo. The symlink bridges the two: edit and commit in the repo, use from anywhere.

```
~/.claude/skills/branch-cleanup -> ~/dev/claude-workflows/skills/branch-cleanup/
```

Changes to a skill file in the repo are immediately live — no copy or sync step. For the full three-tier sync architecture (repo, global, Cowork), see [Skill Management](workflows/skill-management.md).

- [`/pr-review`](skills/pr-review/SKILL.md) — AI-assisted GitHub PR review with line-level draft comments
- [`/pr-review-batching`](skills/pr-review-batching/SKILL.md) - stage PR review comments as drafts on a pending review (never publishes); owns ensure-then-append and accidental-publish incident response
- [`/memory-audit`](skills/memory-audit/SKILL.md) — reflective review, consolidation, and pruning of memory files; defaults to current project, offers a cross-project sweep for promotion candidates
- [`/branch-cleanup`](skills/branch-cleanup/SKILL.md) — interactive local branch cleanup with PR cross-referencing
- [`/grill-me`](skills/grill-me/SKILL.md) — stress-test a plan or design through relentless interrogation
- [`/write-a-prd`](skills/write-a-prd/SKILL.md) — interactive PRD creation through interview, codebase exploration, and module design
- [`/prd-to-issues`](skills/prd-to-issues/SKILL.md) — break a PRD into GitHub issues using tracer-bullet vertical slices
- [`/milestone-to-tasks`](skills/milestone-to-tasks/SKILL.md) — generate a structured `tasks.json` + `progress.md` from a GitHub milestone, ready for a Ralph-style loop
- [`/work-next-task`](skills/work-next-task/SKILL.md) — one iteration of a Ralph loop over `tasks.json`: pick, work, verify, commit. Ships with `scripts/ralph.sh` reference harness
- [`/tdd`](skills/tdd/SKILL.md) — test-driven development with red-green-refactor loop and reference guides
- [`/review-thorough`](skills/review-thorough/SKILL.md) — wraps built-in `/review` and additionally evaluates bot reviews including resolved threads
- [`/security-audit`](skills/security-audit/SKILL.md) — three-phase source-code vulnerability scan (dep audit, parallelized source review, verification + false-positive triage) with GitHub issue tracking
- [`/check-npm`](skills/check-npm/SKILL.md) - audit a JS/TS repo's npm/yarn/pnpm config for supply-chain hardening (lifecycle scripts, git deps, ignore-scripts, min-release-age)
- [`/improve-codebase-architecture`](skills/improve-codebase-architecture/SKILL.md) - repo-wide architecture review: scan for deepening opportunities, render them as a visual HTML report, then grill through the one you pick (adapted from [mattpocock/skills](https://github.com/mattpocock/skills))
- [`/codebase-design`](skills/codebase-design/SKILL.md) - shared deep-module vocabulary (module, interface, depth, seam, adapter, leverage, locality) plus deepening and design-it-twice guides; underpins `/improve-codebase-architecture`
- [`/domain-modeling`](skills/domain-modeling/SKILL.md) - build and sharpen a project's domain model (`CONTEXT.md` glossary, `docs/adr/` decisions); companion to `/improve-codebase-architecture`
- [`/grilling`](skills/grilling/SKILL.md) - Matt Pocock's decision-tree grilling loop, kept distinct from the customized `/grill-me` so the architecture skills can call it by name

### Rules

Rules in `config/rules/` are symlinked into `~/.claude/rules/`, making them globally active across all projects. Like skills, edits in the repo are immediately live.

```
~/.claude/rules/memory-session-exit.md -> ~/dev/claude-workflows/config/rules/memory-session-exit.md
```

- [Memory Session Exit](config/rules/memory-session-exit.md) — audit and update project memories before ending any substantive session
- [Memory Hygiene](config/rules/memory-hygiene.md) — guidelines for memory file size, deduplication, and lifecycle
- [Self-Correction Loop](config/rules/self-correction-loop.md) — on correction, propose a CLAUDE.md or rule update before continuing
- [Epistemic Honesty](config/rules/epistemic-honesty.md) — label verified vs inferred vs assumed; self-challenge before committing to conclusions

### Hooks

Hook scripts in `config/hooks/` are symlinked into `~/.claude/hooks/`. Unlike skills and rules, a hook script is inert until it is *wired* to an event in `~/.claude/settings.json` (a machine-local file that is **not** tracked in this repo). Provisioning a hook is therefore two steps: symlink the script, then add its `hooks` entry (event + matcher) to `settings.json`.

```
~/.claude/hooks/block-em-dash.sh -> ~/dev/claude-workflows/config/hooks/block-em-dash.sh
```

- [`block-em-dash.sh`](config/hooks/block-em-dash.sh) - PreToolUse hook enforcing the no-em-dash rule. Requires matcher `Write|Edit|Bash` in `settings.json` so it inspects the inline Bash command string (`gh`/`git` titles, commit subjects), not just `Write`/`Edit`. Tested via [`block-em-dash.test.sh`](config/hooks/block-em-dash.test.sh) (`bash config/hooks/block-em-dash.test.sh`).
- [`block-claude-attribution.sh`](config/hooks/block-claude-attribution.sh) - PreToolUse hook blocking Claude attribution footers and `Co-Authored-By` trailers.

Because the matcher wiring lives in untracked `settings.json`, a committed hook will not fire for anyone who has not mirrored the matcher locally. Tracking that drift is [#24](https://github.com/dgowrie/claude-workflows/issues/24).

### Agents

Subagent definitions in `agents/` are symlinked into `~/.claude/agents/`, making them available to the Agent tool across all projects. Like skills and rules, edits in the repo are immediately live.

```
~/.claude/agents/pr-code-reviewer.md -> ~/dev/claude-workflows/agents/pr-code-reviewer.md
```

- [`pr-code-reviewer`](agents/pr-code-reviewer.md) - isolated, memory-backed code reviewer for pre-push local diffs (no PR required), fresh-context PR analysis, or standalone bot-comment triage. Analysis-only: returns findings and a recommended next action against the global CLAUDE.md guidelines and rules, applying epistemic-honesty labeling; the main conversation makes any GitHub writes. For a normal stage-and-submit PR review, use the `/pr-review` skill directly. Has persistent user-scoped memory.

## Improvements to consider

### Sync infrastructure

- **Lockfile for concurrent runs** — launchd WatchPaths can fire multiple events for a single operation, risking two script instances racing on the same directory (partial moves, broken symlinks). Add a lockfile or pidfile guard.
- **Invert the Cowork built-ins skip list** — currently a hardcoded list of names; breaks silently if Cowork adds new built-ins. Alternative: only migrate skills with a known marker (e.g., frontmatter field or naming convention) instead of skipping known built-ins.
- **Symlink chain validation** — add an end-to-end check at the end of the sync script: for each repo skill, verify the chain resolves through all three tiers. Log warnings for broken links.
- **Log rotation** — `sync-skills.log` grows forever. Add a size/line check to the script (truncate when over threshold) or configure `newsyslog`.
- **Auto-symlink for new skills** — adding a skill to the repo requires a manual `ln -s` into `~/.claude/skills/`. Add a step to the sync script (or a standalone helper) that scans `skills/*/SKILL.md` and ensures a corresponding symlink exists.

### CLAUDE.md hygiene

- **Triage the follow-ups list** — the Self-Correction Loop section in `~/.claude/CLAUDE.md` has open follow-ups. Some are actionable now (session-start memory report), others are speculative. Prioritize or prune before the list becomes a stale backlog.
- ~~**Version-control global CLAUDE.md**~~ — Done. Tracked at `config/CLAUDE.md`, symlinked to `~/.claude/CLAUDE.md`.
- **Refine commit-authoring guidance** ([#46](https://github.com/dgowrie/claude-workflows/issues/46)) - the inline Git Conventions in `config/CLAUDE.md` has gaps (commit splitting, ordering/narrative, folding out corrective churn, body/footer/scope conventions). Consider extracting into a dedicated `config/rules/` file. Firm constraint: whatever lands must stay concise to limit context-window cost.

### Skills

- **Evaluate replacing `/pr-review` with Cowork's `/review`** — our custom skill had a repo-resolution bug (given a grafana-adaptivelogs-app PR, it cloned and worked in adaptivetraces-app, took many turns to self-correct). Cowork's built-in `/review` may handle repo context better. However, the two skills surfaced different feedback, so the right move is likely to consolidate the best of both rather than a straight swap.
