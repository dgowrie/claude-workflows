# Memory & Context Management — How Claude Handles Memory at Runtime

How memory files impact token usage, the two-tier loading mechanism, and practical strategies for keeping it efficient.

---

## The Two-Tier System

Memory uses a cheap-index, expensive-payload design.

### Tier 1: Always loaded

`MEMORY.md` (the index) is injected into every session's context automatically. Each entry is a one-line summary (~150 chars). This is the memory system's only guaranteed token cost per session.

It is not the session's only always-loaded context. The CLAUDE.md hierarchy (global, project, local), every file in `~/.claude/rules/`, and the description of every model-invocable skill all load unconditionally, and together they typically outweigh the index. This page scopes to memory; budget the rest separately.

- **200-line hard cap** — lines beyond 200 are truncated and invisible to Claude
- **25,000-byte cap** on the spliced index, checked independently of the line cap
- At ~150 chars per line, a full index is roughly 7-10K tokens

The two caps cross at 125 chars per entry (25,000 / 200). Above that average the byte cap binds first and the line cap is never reached; below it, the reverse. That break-even is arithmetic on the two verified constants, so it holds whatever the real average turns out to be.

Measured against the memory indexes on this machine (13 entries across all projects, mean 188.5 chars, max 264), the byte cap binds first with roughly 1.5x margin, so 25KB is the ceiling that matters here. That is one small corpus, not a general result. Compare your own index against the 125 break-even rather than inheriting the number.

> **Provenance.** The two caps above were read out of the Claude Code binary at v2.1.226 (checked 2026-08-07): the truncation notice Claude receives is templated from a `lineCap` constant of 200, and the index size warning uses a `spliceCap` of 25000 bytes. Everything else on this page (the ~150 chars/line average, the token figures, the scaling table's experience column) is estimate, not measurement. The 125-char break-even is derived from the two constants rather than estimated, so it carries their confidence; the 188.5-char mean is a measurement of one machine's indexes, not a general figure. Re-check the constants when Claude Code minor versions move.

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
| "CSS findings" | "Collapse component DOM structure and Emotion cx() override strategies for a given issue" |

### File sizing

- Aim for under 1KB per memory file — enough for context, not a full document
- If a memory exceeds 2KB, consider whether it should be a plan or repo document instead
- This page is the worked example: several KB of reasoning, so it lives here as a repo document, while the sub-1KB `config/rules/memory-hygiene.md` carries the directive that actually loads into sessions

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
