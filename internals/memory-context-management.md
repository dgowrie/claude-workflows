# Memory & Context Management — How Claude Handles Memory at Runtime

How memory files impact token usage, the two-tier loading mechanism, and practical strategies for keeping it efficient.

---

## The Two-Tier System

Memory uses a cheap-index, expensive-payload design.

### Tier 1: Always loaded

`MEMORY.md` (the index) is injected into every session's context automatically. Each entry is a one-line summary (~150 chars). This is the only guaranteed token cost per session.

- **200-line hard cap** — lines beyond 200 are truncated and invisible to Claude
- **25,000-byte cap** on the spliced index, checked independently of the line cap
- At ~150 chars per line, a full index is roughly 7-10K tokens

At that average line length the byte cap binds first: 200 lines x 150 chars is ~30KB, past the 25KB budget. Treat 25KB, not 200 entries, as the practical ceiling.

> **Provenance.** The two caps above were read out of the Claude Code binary at v2.1.226 (checked 2026-08-07): the truncation notice Claude receives is templated from a `lineCap` constant of 200, and the index size warning uses a `spliceCap` of 25000 bytes. Everything else on this page (the ~150 chars/line average, the token figures, the scaling table's experience column) is estimate, not measurement. Re-check the constants when Claude Code minor versions move.

### Tier 2: Loaded on demand

Individual memory files are **not** read automatically. Claude sees the index summaries and decides whether to open each file based on relevance to the current task. Each read is a tool call that adds tokens to context.

```
Session starts
  → MEMORY.md loaded (always)
  → Claude scans summaries
  → Reads only files that seem relevant to the task
  → Skips the rest (zero token cost for skipped files)
```

---

## Tradeoffs

| Concern | Impact | Mitigation |
| --- | --- | --- |
| **Index bloat** | Always-loaded cost grows linearly with entries; truncates past 200 | Prune aggressively, merge related memories |
| **False reads** | Vague descriptions cause unnecessary file reads, wasting context | Write specific, filterable index descriptions |
| **False skips** | Claude misses a relevant memory because the summary didn't signal it | Precise descriptions that name the domain/feature/issue |
| **In-session accumulation** | Read files stay in context until compression kicks in | Keep individual files concise; avoid reading many large files early |
| **Cross-project blindness** | Memories are project-scoped — no cross-pollination | Global rules go in CLAUDE.md, not memory |

---

## Practical Guidelines

### Index descriptions are the relevance filter

They're the only thing Claude sees before deciding to read or skip. Quality here determines the entire system's effectiveness.

| Bad | Good |
| --- | --- |
| "project context notes" | "React 19 upgrade plan for issue #607, PR #652" |
| "testing feedback" | "Integration tests must hit real DB, not mocks — prior prod incident" |
| "CSS findings" | "Grafana Collapse DOM structure and Emotion cx() override strategies for #474" |

### File sizing

- Aim for under 1KB per memory file — enough for context, not a full document
- If a memory exceeds 2KB, consider whether it should be a plan or repo document instead
- The React 19 upgrade plan memory (4.6KB) is an example of something better suited to the `claude-workflows` repo

### Scaling expectations

| Memory count | Index cost | Experience |
| --- | --- | --- |
| 1-20 | Negligible (~1-3K tokens) | Clean, fast relevance matching |
| 20-50 | Modest (~3-7K tokens) | Works fine with good descriptions |
| 50-100 | Notable (~7-15K tokens) | Noisier signals, more false reads |
| 100-200 | Significant (~15-30K tokens) | Approaching the cap, pruning essential |
| 200+ | Truncated | Entries beyond 200 are invisible |

(Row boundaries are line-count based; the 25KB byte cap can bite earlier if descriptions run long.)

---

## Derived artifacts

This page is the rationale source for three things that encode its numbers. Change a threshold here and update all three:

| Artifact | What it inherits |
| --- | --- |
| [`config/rules/memory-hygiene.md`](../config/rules/memory-hygiene.md) | The 1KB / 2KB file sizing, prune-and-dedupe posture, index description quality bar |
| [`config/rules/memory-session-exit.md`](../config/rules/memory-session-exit.md) | The staleness and consolidation checks, driven by index bloat cost |
| [`skills/memory-audit/SKILL.md`](../skills/memory-audit/SKILL.md) | The audit procedure; its stated goal is keeping the two-tier system efficient |

Both rules are symlinked into `~/.claude/rules/` and load into every session, so they carry the directives without the reasoning. The reasoning lives here.
