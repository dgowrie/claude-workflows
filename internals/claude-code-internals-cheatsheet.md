# Claude Code Internals — Cheat Sheet & Learnings

A practical guide to how Claude Code manages state, memory, and context across sessions.

---

## Directory Map

`~/.claude/` is Claude Code's configuration root. Everything lives here.

### You should interact with these

| Path | What it is | When to touch it |
| --- | --- | --- |
| `CLAUDE.md` | Global behavioral rules — always loaded | Add/edit rules, self-correction loop, preferences |
| `settings.json` | Permissions, hooks, env vars | Configure via `/update-config` or edit directly |
| `config.json` | Core config (model, theme) | Rarely — usually set via CLI |
| `projects/*/memory/` | Per-project memories (markdown + frontmatter) | Curate, prune stale entries, seed manually, promote to CLAUDE.md |
| `plans/` | Session plans (markdown, whimsical names) | Resume interrupted work, review past decisions, clean up completed plans |
| `skills/` | Custom skill definitions (`SKILL.md` files) | Create new skills (e.g., `/correct`) |
| `plugins/` | Plugin management | `installed_plugins.json` and `blocklist.json` are the actionable files |
| `backups/` | Timestamped config backups | Restore if a config change breaks something |

### Internal plumbing (don't touch)

| Path | Purpose |
| --- | --- |
| `todos/` | In-session task tracking scratchpad (ephemeral, per-agent) |
| `session-env/` | Captured shell environment per session |
| `sessions/` | Active session lock files (PID-based) |
| `shell-snapshots/` | Zsh/bash profile snapshots for initialization |
| `file-history/` | Undo/redo versioned file snapshots |
| `cache/` | Cached data (changelog, etc.) |
| `ide/` | IDE integration lock files |
| `telemetry/` | Failed telemetry event queue |
| `debug/` | Debug trace logs |
| `paste-cache/` | Clipboard paste content cache |

---

## Memory System

### How it works

- Memories are **markdown files with frontmatter**, stored in `projects/<encoded-path>/memory/`
- `MEMORY.md` is the **index** — one-line summaries that Claude reads at session start
- Claude reads the index every session; reads individual files only if they seem relevant
- **Scoped per project directory** — memories in project A are invisible when working in project B

### Memory types

| Type | Purpose | Example |
| --- | --- | --- |
| `feedback` | Behavioral corrections and confirmed approaches | "Don't add Co-Authored-By unless fully agentic session" |
| `project` | Contextual knowledge not derivable from code | "React 19 upgrade plan — PR #652, merged, follows sibling plugin pattern" |
| `user` | User profile — role, expertise, preferences | "Deep Go expertise, new to React frontend" |
| `reference` | Pointers to external systems | "Pipeline bugs tracked in Linear project INGEST" |

### Tradeoffs and limitations

| Concern | Detail |
| --- | --- |
| **Scoping** | Project-directory-scoped. Global lessons need CLAUDE.md, not memory |
| **Staleness** | No expiry or auto-cleanup. Shipped project memories become dead weight |
| **Conflicts** | A memory can contradict CLAUDE.md or another memory. No resolution mechanism |
| **Truncation** | MEMORY.md index truncates past 200 lines |
| **Best-effort** | Claude is instructed to read/write memories, but there's no guarantee it does |

### Maintenance habits

- **Prune** completed project memories (shipped features, resolved bugs)
- **Promote** recurring feedback memories to CLAUDE.md rules
- **Seed** memories manually when Claude keeps rediscovering the same thing
- **Correct** bad memories directly — faster than hoping Claude self-corrects

---

## Plans

### How they work

- Markdown files in `plans/` with whimsical generated names (e.g., `clever-prancing-goblet.md`)
- Created when Claude enters plan mode during a session
- Serve as working documents: Claude writes the plan, user approves, Claude executes
- **Not automatically reloaded** across sessions — they persist on disk but Claude doesn't read old plans unless asked

### What they capture

- Implementation blueprints — step-by-step, file-level changes
- Situational snapshots — current state when things go sideways, what needs to happen next
- Decision rationale — *why* an approach was chosen (often not in code or commits)

### Practical use

- **Resume work**: "Read `plans/toasty-gathering-elephant.md` and pick up where we left off"
- **Review decisions**: Plans capture reasoning that doesn't survive into code
- **Pre-write plans**: Write a plan file yourself and tell Claude to execute it
- **Clean up**: Delete plans for completed work; promote durable rationale to memories or comments

---

## Self-Correction Loop

The mechanism for Claude to learn from mistakes across sessions.

### The problem

Each session starts fresh. Claude has no recollection of past corrections unless something was written to disk. In practice, corrections often get lost — Claude prioritizes continuing the task, treats the correction as session-local, or the session ends before circling back.

### The fix (two layers)

| Layer | Scope | Durability | Reliability |
| --- | --- | --- | --- |
| **CLAUDE.md rules** | Global or per-project | Permanent until edited | High — always loaded |
| **Feedback memories** | Per project directory | Until manually pruned | Medium — best-effort read |

### Making it reliable

1. **Immediate, mandatory edits** — CLAUDE.md instruction requires Claude to stop the current task and propose a rule edit when corrected (not defer it)
2. **Explicit prompting** — say "add this to CLAUDE.md" when correcting, to force the edit in-session
3. **Periodic review** — run dedicated sessions to promote feedback memories to CLAUDE.md rules

### Further improvements to explore

- **Custom `/correct` skill** — one-command trigger for the full correction flow
- **Session-end hook** — auto-prompt Claude to review corrections before session closes
- **Memory-to-CLAUDE.md promotion sessions** — systematic review across all project memories

---

## Key Takeaways

1. **CLAUDE.md is the only reliable persistence mechanism.** It's always loaded, globally scoped, and human-editable. Everything else is best-effort or project-scoped.
2. **Memories are useful but fragile.** They fill the gap between ephemeral session context and durable CLAUDE.md rules. Treat them as a staging area, not a permanent store.
3. **Plans are underused across sessions.** They're the best record of *why* decisions were made, but they don't resurface automatically. Name them in your memory index or reference them explicitly when resuming work.
4. **Self-correction requires forcing functions.** Instructions alone aren't enough — combine mandatory CLAUDE.md edits, explicit user prompts, and periodic review to close the loop.
5. **Most of `~/.claude/` is plumbing.** Of ~15 directories, only 6-8 are worth interacting with directly. The rest is internal state management.
