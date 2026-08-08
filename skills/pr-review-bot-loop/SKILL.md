---
name: pr-review-bot-loop
description: >
  Drives your own PR to a clean automated-reviewer pass before you request human review: poll for
  the bot's verdict, triage what it posted and what it suppressed, fix, push, re-request, repeat.
  Implements a five-signal adapter contract (re-request / pending? / landed? / clean? / suppressed?)
  against Copilot, whose real findings hide in a collapsed block in the review body where every
  other signal reports clean. Self-review only; it never touches someone else's PR and never merges.
  Trigger phrases: "drive this PR to a clean bot pass", "loop until Copilot is happy", "bot review
  loop", "did Copilot actually review the latest commit", "check for suppressed comments", "is this
  PR ready for human review", or explicit `/pr-review-bot-loop`.
---

# PR Review Bot Loop

A self-paced loop that drives **your own** PR to a state where the automated reviewer has nothing
left to say, so a human reviewer spends their attention on design rather than on what a bot would
have caught.

It composes with its siblings rather than absorbing them. `/pr-review` finds and formats,
`/pr-review-adversarial` decides what survives, `/pr-review-batching` stages. This skill owns the
one thing none of them do: the round trip with a reviewer that answers on its own schedule, in a
surface that hides half of what it found.

---

## When to run it

Run it on a PR you authored, after your own review pass, before requesting human review.

Skip it when the bot has no opinion worth waiting for. On a prose-heavy diff, a clean Copilot round
is **weak evidence**: measured across three rounds on a 280-line `SKILL.md`, Copilot produced
exactly one finding, a grammar nit, while an adversarial pass over the same file produced two
upgrades and a reinstated dismissal. Copilot's review is oriented at code. Run the loop anyway if
you want the coverage, and report the result as "no automated objection" rather than as evidence of
quality.

**Self-review only.** Someone else's PR is out of scope in both directions: you cannot push the
fixes, and driving a reviewer at their branch is noise they did not ask for. For a peer PR, use
`/pr-review` and stage findings through `/pr-review-batching`.

---

## Inputs

| Input | Values | Default |
| --- | --- | --- |
| `pr` | PR URL or number | required |
| `poll` | Seconds between wakeups | `90` |
| `max_rounds` | Hard backstop on loop rounds | `5` |
| `nit_rounds` | Consecutive trivial-only rounds before surfacing it to the user | `2` |

All four are parameters. Reading them from the invocation is the point; a hardcoded poll interval
is what makes a loop expensive on a fast bot and blind on a slow one.

Confirm authorship before the first round: compare `author.login` from `gh pr view` against
`gh api user --jq .login`. Use `dangerouslyDisableSandbox: true` for `gh` (corporate proxy TLS).

---

## The adapter contract

Five signals. A bot adapter implements all five or it is not an adapter, because the four-signal
version terminates early and ships defects (see The suppressed signal).

| Signal | Question |
| --- | --- |
| `re-request` | Ask the bot to review the current head |
| `pending?` | Is a request outstanding right now |
| `landed?` | Does a review exist whose commit is the current head |
| `clean?` | Did that review post actionable comments |
| `suppressed?` | Did that review withhold findings it judged low-confidence |

**Copilot is the only implemented adapter.** CodeRabbit, Codex, Sourcery, and Gemini Code Assist
differ in every one of the five, including whether they re-review on push at all. Treat them as
unimplemented and say so rather than assuming Copilot's mechanics generalize; the traps below were
all measured, and guessing the equivalents for another bot reproduces none of that work.

---

## The Copilot adapter

`landed?` and `suppressed?` ship as a script, since between them they carry every measured trap:

```bash
~/.claude/skills/pr-review-bot-loop/scripts/copilot-signals.py <owner> <repo> <pr-number>
```

That is the installed path, and it is the one to use: the loop runs from the target project's
working directory, which is usually not this repo. The repo-relative paths further down are
deliberate, and they apply only when you are editing the detector itself.

Exit `0` clean, `1` triage-required, `2` not-applicable, `3` error. It prints the pending request,
every Copilot review with its commit, inline count, and suppressed findings. Exit `3` is a signal
that the query failed, so it carries **no verdict**; fix it and re-run rather than reading it as any
of the other three.

The remaining signals are single commands:

| Signal | Command |
| --- | --- |
| `re-request` | `gh pr edit <n> --add-reviewer @copilot` |
| `re-request` (fallback) | `gh api -X POST repos/{owner}/{repo}/pulls/{n}/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'` |
| `pending?` | GraphQL `reviewRequests`, which the script already reports |
| `clean?` corroboration | review `bodyText` contains "generated no new comments"; zero review threads created after its `submittedAt` |

Four traps, each measured, each of which silently breaks a loop built without it:

- **GraphQL is the only surface that shows a pending Copilot request.** Both `gh pr view --json
  reviewRequests` and REST `/pulls/{n}/requested_reviewers` return empty while one is outstanding.
  An adapter reading either sees a false "nothing pending", re-requests over its own live request,
  and can loop forever.
- **Copilot's login differs by surface**: `copilot-pull-request-reviewer` in GraphQL,
  `copilot-pull-request-reviewer[bot]` in REST, and plain `Copilot` in the re-request response.
  Match a substring or an explicit set of all three. Building the poll filter from the re-request
  response's value was measured to hang a watcher straight through a landed review, a failure that
  looks exactly like latency.
- **The REST fallback needs the `[bot]` suffix.** Without it the call returns `422 Reviews may only
  be requested from collaborators`, which reads as a permissions problem and is really a name format
  problem.
- **Reviews authored by the PR author are artifacts, not verdicts.** Every `:zap:` thread reply
  posted over REST creates an empty-bodied `COMMENTED` review under your own login. Filter to the
  bot before reading any verdict.

Round latency was roughly 90 seconds to 2 minutes across the measured rounds, which is why `poll`
defaults to 90 rather than the 3-to-7-minute figure in older notes.

---

## The suppressed signal

This is the signal the skill exists for.

Copilot withholds findings it judges low-confidence into a collapsed `<details>` block in the review
**body**. They never become inline comments, so `comments.totalCount`, the "generated no new
comments" body text, and a thread count after `submittedAt` all report clean while real defects sit
unread. On one 5-round PR, **6 of 11 fix commits came from reviews that all three clean signals
called clean**, including a genuine rendering bug and a regression introduced one round earlier.
Reproduced later on a second PR, in a different area, one round after a genuinely clean round.

It is three-state. Collapsing it to a boolean is a bug in opposite directions.

| State | Condition | Loop action |
| --- | --- | --- |
| clean | review at head, nothing posted and nothing suppressed | terminate |
| triage-required | review at head, and any of: inline comments non-zero, suppressed count non-zero or unparsable, or parsed findings disagreeing with a declared count | triage whatever it reported, posted or withheld, then fix, push, re-request |
| not-applicable | no review at head | re-request, or wait if one is pending |

- **Scope the check to the review at `headRefOid`.** A detector that scans every review on the PR
  stays dirty forever, because an already-fixed round's suppressed block remains in the history
  permanently. That failure presents as progress, which makes it worse than terminating early.
- **A not-applicable result is not a clean result.** Head-scoping alone makes them the same value:
  a PR with no review at head suppresses nothing and reads as clean. Copilot does not re-review on
  push, so this is the silent-abandonment trap, and `suppressed?` cannot be evaluated independently
  of `landed?`.
- **An unparsable count is triage-required.** Silent-zero is the exact failure the signal exists to
  prevent, so a parser that cannot read the count reports that, never zero.

Two constraints hold the parser together, both live in `copilot-signals.py`, and both were measured
by running it rather than by reading it. **Match `suppress` plus a parenthesised count**: Copilot has
used at least two labels (`Comments suppressed due to low confidence (N)` and `Suppressed comments
(N)`), so a detector keyed to either literal phrase under-reports on the other, and expect a third.
**Gate on the summary text before parsing the block**: `Show a summary per file` is a benign
`<details>` block living in the same body.

**Validate a detector against a known-positive PR, and across a state transition.** Both parser
traps and both scoping traps were found by running the thing against PRs whose answers were already
known, never by review, and each surfaced only after the previous one was fixed. A single-round test
cannot find them: the head-scoping trap appears only once a fix has landed. A detector validated
only against a clean PR is untested.

That discipline is encoded in `scripts/test_copilot_signals.py`, which pairs synthetic cases for the
states no real PR reaches with known-answer cases against merged PRs whose state can no longer
drift. Run it after any change to the detector:

```bash
python3 -m unittest discover -s skills/pr-review-bot-loop/scripts        # offline
SIGNALS_LIVE=1 python3 -m unittest discover -s skills/pr-review-bot-loop/scripts
```

---

## The loop

Each round:

1. **Read the signals.** Run `copilot-signals.py` and branch on its exit status: `0` go to
   Termination, `1` triage, `2` re-request or wait, `3` fix the query and re-run.

   On `1`, triage only the findings at this head that are **not already dispositioned**. If every
   one of them is, go to Termination. Exit `1` is computed from what the review says, not from what
   you did about it, so declining a finding leaves it at `1` forever; without this clause the loop
   re-triages the same findings until `max_rounds`.
2. **Re-request when no review exists at head and nothing is pending against it.** A request already
   in flight means wait, not re-request; that gate is what keeps you off the double-request trap.
   Head-scoping already encodes "the current commit is unreviewed", so there is no separate
   new-commit condition to check, and the entry case of a PR the bot has never seen qualifies.
3. **Wait** before polling again. Under `/loop` dynamic mode, use `ScheduleWakeup` at `poll`.
   Otherwise run the poll as a background shell command; foreground `sleep` is blocked in this
   harness. Conclude nothing from the wait itself.
4. **Triage every finding, posted and suppressed together.** Route them through
   `/pr-review-adversarial` Phase 2 rather than acting on them directly. Low-confidence items are
   exactly where a refuter earns its cost: of 7 suppressed issues on the measured PR, 2 rested on
   factually wrong premises and would have caused pointless churn.
5. **Fix what survives**, regression test first, per the global TDD convention.
6. **Validate, then push.** If the package manager launcher fails on an engine mismatch, run the
   underlying tools directly (`npx tsc --build`, `npx vitest run`, `npx eslint . --max-warnings=0`);
   a launcher that will not start is a reason to reach past it, never a reason to skip validation.
7. **Reply to the threads** you acted on, then loop.

A push moves head, which makes the next signal read `not-applicable` and sends you to step 2. The
detector drives the loop; you do not track round state separately. The one thing it cannot tell you
is whether you already dispositioned a finding, so record that where the detector's own inputs live:
a published `:zap:` or `:thought_balloon:` reply on the thread, and for a suppressed finding, which
has no thread, the commit message that fixed it or a PR comment declining it. Disposition then lives
on the PR rather than in session memory, and a fresh session picks the loop up mid-flight.

### Thread hygiene

Reply in the format the global PR Review Conventions define. Replies need the **numeric** comment
id, not the GraphQL node id, which 404s: `POST /pulls/{n}/comments/{numericId}/replies`.

**Leave every bot thread open.** An open thread keeps the finding and your response visible for the
human reviewer who comes next. This is the one action the loop must never take, and it is called out
because the instinct while driving toward "clean" is to tidy threads shut; a session following an
earlier version of `/pr-review` did exactly that. Resolve only threads you authored yourself.

Thread replies publish the moment you post them and cannot be staged as drafts
(`/pr-review-batching` Operation 3). Nothing in this loop is a draft.

A suppressed finding has no thread at all, so there is nothing to reply to. Record its disposition in
the commit message that fixes it, or in a PR comment when you decline it.

---

## Termination

Terminate on **no unresolved findings you judge valid**, with `max_rounds` as a hard backstop.

A genuinely empty suppressed queue is not a reachable goal. Measured across four consecutive rounds
that every clean signal called clean, the suppressed count ran 1, 4, 2, 1: it refilled rather than
drained, and the largest round was the third. A loop whose stopping condition is "the bot goes
quiet" may not have a fixed point, so the judgment call is the condition and the round cap is what
makes it terminate regardless.

When `nit_rounds` consecutive rounds produce only trivial findings, surface that to the user and
keep going. Hitting `max_rounds` stops the loop and is a result to report, not a failure to retry.

Report the outcome as a readiness statement: rounds run, findings accepted and declined per round,
the terminating state, and what the clean pass is worth on this diff.

---

## At scale: stacked PRs

Documentation, not automation. This skill drives one PR.

Give each PR in a stack its own git worktree on its own branch and run one loop per worktree. Push
fixups only to that PR's assigned branch: a fix in a lower PR does not propagate up the stack on its
own, so re-syncing the branches above it is a deliberate follow-up. Land the stack bottom-up.

---

## Out of scope

**Merge.** This loop ends at a readiness report and stops. Merge gating (authorization, base-ref
checks, closing-keyword detection, telling "no checks configured" apart from "checks pending") is
owned by `/pr-review`'s self-review mode, which calls this loop rather than the reverse.

**Finding validation.** Step 4 hands off to `/pr-review-adversarial` and consumes its verdicts.

**Convergence across both passes.** This loop converges the bot. A caller that alternates bot rounds
with adversarial rounds owns the combined stopping condition, and must consume the three-state
result rather than a boolean: a `not-applicable` round means the bot pass did not run, which is
neither "nothing new" nor "something new", and reading it as the former converges on an unreviewed
head.

---

## Cost and known weaknesses

- **Cost is wall clock, not tokens.** A round is one script run, one wakeup, and whatever the fixes
  need. The expensive part is step 4's adversarial dispatch, at `1 + ceil(candidates / 10)`
  subagents per round.
- **The parser is pattern-matched against an undocumented format.** Copilot's body markup is not an
  API. It has already changed label once. When the parsed finding count disagrees with the declared
  count the script warns and you read the body directly; treat that warning as the format having
  moved.
- **A clean pass is not evidence the diff is good**, and on prose it is barely evidence of anything.
  It means one automated reviewer, oriented at code, raised no objection at this head.
- **One adapter.** Every mechanic here is Copilot's. A repo whose automated reviewer is something
  else gets no coverage from this skill until its adapter is written.

---

## Notes

- Global conventions (PR Review Conventions, TDD, Definition of Done, commit and dash rules) live in
  the global `CLAUDE.md` and `~/.claude/rules/`. This skill obeys them and points at them rather
  than copying them. The one repetition it does carry is deliberate: leaving bot threads open is
  restated here because driving toward "clean" is exactly the context that tempts you past it.
- Related: `/pr-review` (find and format), `/pr-review-adversarial` (validate findings),
  `/pr-review-batching` (stage, never publish).
