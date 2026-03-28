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

### Skills

- [`/pr-review`](skills/pr-review/SKILL.md) — AI-assisted GitHub PR review with line-level draft comments
- [`/memory-audit`](skills/memory-audit/SKILL.md) — periodic review and pruning of memory files across all projects

## Improvements to consider

### Sync infrastructure

- **Lockfile for concurrent runs** — launchd WatchPaths can fire multiple events for a single operation, risking two script instances racing on the same directory (partial moves, broken symlinks). Add a lockfile or pidfile guard.
- **Invert the Cowork built-ins skip list** — currently a hardcoded list of names; breaks silently if Cowork adds new built-ins. Alternative: only migrate skills with a known marker (e.g., frontmatter field or naming convention) instead of skipping known built-ins.
- **Symlink chain validation** — add an end-to-end check at the end of the sync script: for each repo skill, verify the chain resolves through all three tiers. Log warnings for broken links.
- **Log rotation** — `sync-skills.log` grows forever. Add a size/line check to the script (truncate when over threshold) or configure `newsyslog`.

### CLAUDE.md hygiene

- **Triage the follow-ups list** — the Self-Correction Loop section in `~/.claude/CLAUDE.md` has 6 open follow-ups. Some are actionable now (memory-audit deployment, session-start memory report), others are speculative. Prioritize or prune before the list becomes a stale backlog.
