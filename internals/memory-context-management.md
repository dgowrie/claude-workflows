# Memory & Context Management — How Claude Handles Memory at Runtime

How memory files impact token usage, the two-tier loading mechanism, and practical strategies for keeping it efficient.

---

## The Two-Tier System

Memory uses a cheap-index, expensive-payload design.

### Tier 1: Always loaded

`MEMORY.md` (the index) is injected into every session's context automatically. Each entry is a one-line summary (~150 chars). This is the only guaranteed token cost per session.

- 200-line hard cap — lines beyond 200 are truncated and invisible to Claude
- At ~150 chars per line, a full index is roughly 7-10K tokens

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
