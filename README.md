# claude-workflows

A personal knowledge base for how I work with Claude Code — the learnings, patterns, and tools that accumulate through daily use but have no natural home.

Claude Code's built-in persistence (memory, plans) is useful but fragile: memories are project-scoped and best-effort, plans don't resurface automatically, and corrections made in one session often don't survive to the next. This repo is the durable layer on top — a place to capture what I've learned, share it with peers, and build on it over time.

## Structure

```
internals/     How Claude Code works under the hood
workflows/     Patterns and practices for effective use
explorations/  Session notes and behavioral findings
skills/        Skill drafts before deploying to ~/.claude/skills/
```

## Contents

### Internals

- [Claude Code Internals — Cheat Sheet](internals/claude-code-internals-cheatsheet.md)
- [Claude Code Internals — Presentation](internals/claude-code-internals-presentation.html) (Reveal.js, open in browser)
- [Memory & Context Management](internals/memory-context-management.md) — how memory impacts token usage, two-tier loading, scaling guidelines

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
- [`/memory-audit`](skills/memory-audit/SKILL.md) — periodic review and pruning of memory files across all projects
- [`/branch-cleanup`](skills/branch-cleanup/SKILL.md) — interactive local branch cleanup with PR cross-referencing
- [`/grill-me`](skills/grill-me/SKILL.md) — stress-test a plan or design through relentless interrogation
- [`/write-a-prd`](skills/write-a-prd/SKILL.md) — interactive PRD creation through interview, codebase exploration, and module design
- [`/prd-to-issues`](skills/prd-to-issues/SKILL.md) — break a PRD into GitHub issues using tracer-bullet vertical slices
- [`/milestone-to-tasks`](skills/milestone-to-tasks/SKILL.md) — generate a structured `tasks.json` + `progress.md` from a GitHub milestone, ready for a Ralph-style loop
- [`/work-next-task`](skills/work-next-task/SKILL.md) — one iteration of a Ralph loop over `tasks.json`: pick, work, verify, commit. Ships with `scripts/ralph.sh` reference harness
- [`/tdd`](skills/tdd/SKILL.md) — test-driven development with red-green-refactor loop and reference guides
- [`/review-thorough`](skills/review-thorough/SKILL.md) — wraps built-in `/review` and additionally evaluates bot reviews including resolved threads

## Improvements to consider

### Sync infrastructure

- **Lockfile for concurrent runs** — launchd WatchPaths can fire multiple events for a single operation, risking two script instances racing on the same directory (partial moves, broken symlinks). Add a lockfile or pidfile guard.
- **Invert the Cowork built-ins skip list** — currently a hardcoded list of names; breaks silently if Cowork adds new built-ins. Alternative: only migrate skills with a known marker (e.g., frontmatter field or naming convention) instead of skipping known built-ins.
- **Symlink chain validation** — add an end-to-end check at the end of the sync script: for each repo skill, verify the chain resolves through all three tiers. Log warnings for broken links.
- **Log rotation** — `sync-skills.log` grows forever. Add a size/line check to the script (truncate when over threshold) or configure `newsyslog`.
- **Auto-symlink for new skills** — adding a skill to the repo requires a manual `ln -s` into `~/.claude/skills/`. Add a step to the sync script (or a standalone helper) that scans `skills/*/SKILL.md` and ensures a corresponding symlink exists.

### CLAUDE.md hygiene

- **Triage the follow-ups list** — the Self-Correction Loop section in `~/.claude/CLAUDE.md` has 6 open follow-ups. Some are actionable now (memory-audit deployment, session-start memory report), others are speculative. Prioritize or prune before the list becomes a stale backlog.
- ~~**Version-control global CLAUDE.md**~~ — Done. Tracked at `config/CLAUDE.md`, symlinked to `~/.claude/CLAUDE.md`.

### Skills

- **Evaluate replacing `/pr-review` with Cowork's `/review`** — our custom skill had a repo-resolution bug (given a grafana-adaptivelogs-app PR, it cloned and worked in adaptivetraces-app, took many turns to self-correct). Cowork's built-in `/review` may handle repo context better. However, the two skills surfaced different feedback, so the right move is likely to consolidate the best of both rather than a straight swap.
