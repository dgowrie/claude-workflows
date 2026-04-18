# Milestone-driven Ralph skill vs. AIHero Ralph conventions

**Date:** 2026-04-17
**Context:** Design comparison captured during the grill-me session for `milestone-to-tasks` + `work-next-task` skills. Retained for product roadmapping review.

## Sources

- <https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum>
- <https://ghuntley.com/ralph/>
- <https://www.aihero.dev/getting-started-with-ralph>

## What AIHero / Huntley Ralph provides

A **pattern plus a script**. Key deliverables:

- Two reference shell harnesses: `ralph-once.sh` (HITL, single invocation) and `afk-ralph.sh` (Docker sandbox, fully autonomous)
- The one-line canonical loop: `while :; do cat PROMPT.md | claude-code ; done`
- Bash for-loop variant with iteration cap + `<promise>COMPLETE</promise>` exit signal
- Conventions: `PRD.md` + `progress.txt` + shell script as the three-file foundation
- A prompt template embedded directly in the harness script
- Example task-item shape: `category`, `description`, `steps`, `passes: false` (JSON)

User is responsible for authoring: the PRD, the dependency graph, the priority encoding, the verification conventions, the progress file format, and any GitHub integration they want.

## What our solution provides

Two skills plus a reference harness, driven by an existing GitHub artifact (milestone).

- **`milestone-to-tasks`** (generator): reads a GH milestone, produces `tasks.json` + seeded `progress.md` + a `.gitattributes` entry for `merge=union` on `progress.md`.
- **`work-next-task`** (worker): one-shot iteration — select, drift-check, claim, work, verify, commit.
- **`scripts/ralph.sh`**: capital-R Ralph shell harness invoking the worker skill headlessly.

## Capability / deliverable comparison

| Dimension | AIHero Ralph | Our solution |
|---|---|---|
| What you bring | A hand-written PRD.md + a shell script | A GitHub milestone (already exists in your workflow) |
| Out-of-the-box deliverables | Pattern + ~10-line shell harness | Two skills, reference shell harness, generated task artifact, generated progress log scaffold |
| Task list authoring | You write it yourself, free-form structure | Generator infers structure from milestone issues |
| Priority assignment | You decide, encoded however you like | Inferred from labels → dependency depth → LLM, with user confirmation |
| Dependency graph | You encode it manually in PRD prose | Parsed from "Blocked by" refs + GH sub-issue links + LLM fallback, user-confirmed |
| Verification gates | Free-form prose in PRD | Explicit `steps[]` per task, walked as acceptance gates |
| GitHub integration | None — git-only | Milestone-aware; drift-checked at pickup; auto-syncs closed issues; opens draft PR per task in autonomous mode |
| Status tracking | Whatever convention you put in your PRD | Standardized enum (`open` / `in_progress` / `done`), prompt-enforced transitions |
| Progress log shape | Free-form `progress.txt` | Append-only, reverse-chronological, four structured event templates (pickup / success / failure / drift) |
| Branch discipline | Commits to whatever branch you're on | One branch per task, `<user>/<type>_T<id>-<slug>` matching user conventions |
| Concurrency / multi-worker | Single-process by default | Standard mode = single-worker; autonomous mode supports concurrent worktrees via fetch-before-select / push-after-claim |
| Stop conditions | One token (`COMPLETE`), iteration cap, "off the rails" undefined | Five explicit exit conditions, two tokens (`MILESTONE_COMPLETE`, `HALT`), per-task retry cap in config |
| Mid-flight edits | Implicit (you can edit PRD.md) | First-class — `done → open` with revised steps is the documented revision mechanism |
| Run modes | `ralph-once.sh` (HITL) or `afk-ralph.sh` (sandbox) | `/loop /work-next-task` (in-session) or `scripts/ralph.sh` (capital-R Ralph) |
| Artifact lifecycle | Persists until you delete | Ephemeral by design — worker prompts for cleanup when all tasks done |
| Sandbox / fully-AFK | Yes, ships with Docker sandbox variant | Deferred to v1.x — shell harness ships; sandbox composition is on the user |

## The framing difference

**AIHero Ralph is "a pattern plus a script."** Bring your own PRD shape, dep graph, verification, progress conventions, and tracker integration. Maximum flexibility, maximum setup.

**Our solution is "a GH-milestone-driven workflow with batteries included."** Point at a milestone you already have; the generator produces a structured artifact with deps + priorities + verification inferred and user-confirmed; Ralph runs against it. Same loop pattern at the core, less DIY at the edges.

## Tradeoffs we accept

- **More opinionated.** Assumes GH milestones (or, eventually, PRDs as sub-issues) as the source. AIHero's "any task list" generality is sacrificed.
- **More setup surface in v1** (two skills + a harness + symlinks vs. one shell script).
- **Less "fully unattended" out of the box.** AIHero ships Docker sandbox; we defer it.

## Capability gains

- No manual PRD authoring for GH-shop users
- Verification + dep + priority inference instead of hand-encoding
- Drift safety against upstream issue changes
- Multi-worker support across worktrees
- Structured progress and task lifecycle that humans and bots can both reason over
- Composable — the same worker skill works against any future generator (PRD-to-tasks, milestone-to-tasks, etc.)

## Net position

For someone already running GH-milestone-driven work, our solution removes the manual-PRD step Ralph requires and adds GH-native lifecycle handling.

For someone whose work isn't in GH milestones, AIHero's pattern is a better starting point until we ship more generators (PRD-to-tasks, etc.).

## Roadmap implications

Items flagged for v1.x / follow-up based on this comparison:

- **Fully-unattended AFK / sandbox variant.** Docker sandbox wrapper, network scoping, secret mounting, resource limits, wall-clock timeout, cost budget, crash-recovery contract, per-iteration log capture, `AFK` skill integration for notifications.
- **Related generators.** `prd-to-tasks` (PRD with sub-issues → tasks.json) to broaden applicability beyond milestones.
- **Running `/loop` directly against a PRD's sub-issue graph** — skipping `tasks.json` entirely because deps/priorities are already encoded on the issues. Still uses `progress.md`. Separate related skill; does not replace the milestone flow.
- **Soft safety check (v1.1):** warn when another branch has recently modified `tasks.json` to catch accidental concurrent standard-mode runs.
- **Advisory claim files (later):** `claims/<agent-id>.json` with heartbeat if fetch-before-select / push-after-claim proves insufficient under load.
- **CI watch inside the autonomous loop** instead of composing with separate conventions.
- **Three-way merge for `--refresh`** if the v1 conservative-merge approach produces surprises.
