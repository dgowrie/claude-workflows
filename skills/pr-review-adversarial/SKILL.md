---
name: pr-review-adversarial
user-invocable: true
description: >
  Two-phase adversarial validation for PR review findings. Phase 1 attacks the CODE (your own
  skeptical pass over freshly re-fetched state, plus one independent fresh-context
  `pr-code-reviewer` subagent) and unions the candidates. Phase 2 attacks the FINDINGS (a second,
  new `pr-code-reviewer` whose only job is to refute every candidate and every proposed fix,
  defaulting to NOT PROVEN). Catches findings that are wrong, fixes that are unsafe, and
  dismissals that were premature. Works on peer PRs and your own. Trigger phrases: "adversarial
  review", "run an adversarial /pr-review", "refute these findings", "attack this diff",
  "validate these findings before I stage them", "am I sure about these findings", or explicit
  `/pr-review-adversarial`.
---

# PR Review Adversarial

This skill validates review findings before they are acted on. It is the `epistemic-honesty`
rule's "adversarial subagent" section applied to PR review, with one addition learned from
practice: the adversary must attack the **dismissals** too, not only the findings.

It composes with `/pr-review` rather than replacing it. `/pr-review` finds and formats; this skill
decides what survives. It writes nothing to GitHub.

---

## When to run it

Run the whole pass when the cost of shipping a wrong finding or an unsafe fix exceeds a few
subagent dispatches: correctness, security, data safety, API contracts, migrations, anything you
are about to implement rather than merely mention, and any review of a diff you authored yourself.

Skip it only for a diff that is genuinely inert prose or formatting. **This skip clause overrides
the run triggers above**, so state which one you applied. A `SKILL.md`, rule file, agent
definition, or `CLAUDE.md` does not qualify as prose: it is procedure a later session executes
literally, and it earns the full pass.

**There is no gate inside the pass.** Once you are running it, every candidate reaches Phase 2,
including the ones you already decided were cosmetic. That is deliberate: the pattern's biggest
observed win was a refuter upgrading a finding that had been called cosmetic into a real
off-by-one bug, which any severity gate would have excluded. Inside one batch the marginal cost of
carrying a nit is near zero, but it is a step function, not a flat zero: the nit that pushes the
count past the split threshold costs a whole subagent. See Cost and known weaknesses.

---

## Inputs

| Input | Values | Default |
| --- | --- | --- |
| `pr` | PR URL or number | required |
| `mode` | `peer` (someone else's PR) or `self` (yours) | inferred by comparing `author.login` against `gh api user --jq .login`; confirm if ambiguous |
| `findings` | An existing candidate set to validate | empty; Phase 1 produces one |

An existing PR is required, open, closed, or merged. The phase structure hangs off a pinned PR head
SHA, and Phase 1a's bot cross-check has nothing to read without one; neither needs the PR to be
open, and a merged PR's pin cannot move. For pre-PR local work, dispatch `pr-code-reviewer`
directly against the branch diff; that is its own documented niche.

When `findings` is supplied (for example `/pr-review` just ran and produced them), always run Phase
1b, the independent subagent. A candidate set you already hold is exactly the input Phase 1b is
meant to be uncontaminated by. Phase 1a is conditional: if the supplied findings came from a
`/pr-review` pass over Steps 3 through 7 at the same pinned SHA, 1a reduces to re-verifying them
against that SHA; otherwise (older SHA, human-supplied, bot-supplied) run 1a in full, or Phase 1
stops being two reads.

---

## Phase 0: ground truth

Findings anchor to a commit, so pin one before reading anything.

```bash
gh pr view <pr> --json number,headRefOid,baseRefName,author,title,files
gh pr diff <pr>
```

- **Re-fetch, never recall.** Read the committed state even when you wrote the code in this same
  session. Memory of what you intended is not evidence of what you pushed, and it is the main
  authorship-bias failure mode this skill exists to counter.
- Record the head SHA. Every finding cites `path:line` at that SHA.
- If HEAD moves before the pass finishes, the pass is invalid. Re-pin and redo it against the new
  SHA rather than reconciling across two trees. Before Phase 2 that means restarting at Phase 1;
  detected later, it means re-running both phases, since the existing verdicts are now stale.
- Use `dangerouslyDisableSandbox: true` for `gh` (corporate proxy TLS).

---

## Phase 1: additive, attack the CODE

Two independent reads of the same diff. The output is a union, not a consensus.

### 1a. Your own skeptical pass

Follow `/pr-review` Steps 3 through 7 (repo context, PR type, focus areas, bot cross-check
(analysis only), verify-before-flagging). **Skip Step 6's reply and resolve subsections**; they
publish, and this skill writes nothing. Bot threads count as candidate findings here, including
resolved ones; a silent dismissal is a candidate like any other.

Step 3's linter suppression is scoped narrowly here: it applies to formatting the linter already
enforces, which is genuinely not yours to flag. Anything you judged cosmetic on other grounds goes
into `dismissed[]`, not away. Nothing else is filtered before the union.

### 1b. One independent fresh-context reviewer

Dispatch a single `pr-code-reviewer` subagent at the same diff.

- **Do not pass it your findings.** Anchoring it on your candidates is the whole failure this
  phase is built to avoid. Give it the PR ref, the head SHA, and the instruction to review
  independently.
- In `self` mode, do not tell it the diff is yours. This is a constraint on the prompt you write,
  not a guarantee of ignorance: the agent's own fetch surfaces `author`. The point is not to
  foreground it.

### Union and classify

Merge both result sets. Deduplicate by (path, line, claim), not by wording.

Agreement between 1a and 1b is **weak** evidence. Both reads share a model, a prompt lineage, the
same diff, and, where the dispatched agent has user-scoped memory, the same stored review
heuristics. Correlated priors make correlated mistakes. Note corroboration, do not treat it as
verification.

Split the union into two lists that both carry into Phase 2:

- `kept[]` - candidates you would flag. Each carries: id, `path:line`, claim, evidence, proposed
  fix (if any), severity.
- `dismissed[]` - candidates you considered and rejected, cosmetic nits included. Each carries the
  same fields plus **the reason you dismissed it**. Without the reason the refuter has nothing to
  attack.

---

## Phase 2: subtractive, attack the FINDINGS

Re-query `gh pr view <pr> --json headRefOid` first and compare against the pin. Do this before the
dispatch, not after: catching a moved HEAD here saves the subagent, catching it later only saves
you from presenting.

One `pr-code-reviewer`, batched over the whole union. If the union is empty, skip the dispatch and
report per Phase 3; run the HEAD re-query anyway.

**It must be a new instance.** Spawn a fresh agent; do not continue the Phase 1b agent via
`SendMessage`. An agent that authored a finding will confirm it, which produces a verdict with no
information in it. Note the limit of this guarantee: a fresh instance isolates context, not
memory-resident priors (see Cost and known weaknesses).

**The dispatch prompt overrides the agent's defaults.** State in it that this mandate and the
output schema below supersede `pr-code-reviewer`'s own Output Format, and that the job is to
adjudicate the supplied set, not to run `/pr-review` Steps 1 through 7 and return a fresh review.
Without that, the agent follows its definition and hands back a second review instead of verdicts.
The supersession covers **structure only**. The severity vocabulary is retained, since the agent's
Output Format is where it is defined and the schema below requires a severity back.

Phase 2 cannot blind the refuter to authorship the way Phase 1b does: the finding set itself
carries it. The `NOT PROVEN` default and the rubber-stamp check below carry that load instead.

Its mandate:

- Refute every entry in `kept[]` and every entry in `dismissed[]`.
- Attack the **proposed fix** as a separate target from the claim. A correct finding with an unsafe
  fix is the expensive case: one observed run flagged that a proposed NUL-byte (U+0000) key
  separator would be rejected by Postgres `text` columns downstream, where the finding itself was
  fine.
- Attack each dismissal rationale in `dismissed[]` on its own terms.
- **Default to NOT PROVEN.** Uncertainty resolves against the finding, not for it.
- Cite evidence read at the pinned SHA. "Looks like" is not evidence.
- Treat its own stored review heuristics as a source of correlation to discount, not as evidence.

### Verdicts

| Verdict | Meaning | Action |
| --- | --- | --- |
| `REFUTED` | The claim does not hold at the pinned SHA | Drop it, unless you independently verified the claim; then Phase 3 governs |
| `SURVIVES` | The attack failed | Keep as stated |
| `UNDERSTATED` | Real, and worse than stated (severity, blast radius, or root cause) | Upgrade before presenting |
| `REINSTATED` | A `dismissed[]` entry the refuter shows was wrongly dismissed | Promote into `kept[]` at the refuter's severity |

The table above reads against a `kept[]` entry. On a `dismissed[]` entry the same verdicts read
against the dismissal: `SURVIVES` means the dismissal is upheld and it stays dropped, `REFUTED`
means the underlying claim was disproved outright and it stays dropped for a stronger reason,
`REINSTATED` means the dismissal broke. `UNDERSTATED` does not apply to `dismissed[]`; a dismissed
candidate that turns out to be worse than thought is `REINSTATED`.

`UNDERSTATED` and `REINSTATED` are why the pass is worth running. A refuter that only ever returns
`REFUTED` and `SURVIVES` is being used as a rubber stamp.

Required per-finding output: `{id, list, verdict, evidence, revised_fix?}`, plus `severity`
whenever the verdict is `REINSTATED` or `UNDERSTATED`. `list` is required because two of the
verdicts produce the same action from opposite reasoning, so a verdict is unreadable without it.
Severity is required because both of those verdicts re-grade a finding; use the
`blocking / should-fix / nit` scale, which is what `pr-code-reviewer` already emits.

---

## Phase 3: reconcile

The refuter's verdicts are input to your judgment, not a substitute for it. It can be wrong in both
directions.

- Address every verdict: verify it, revise the finding, or record it as an open risk. Never present
  a finding with "though a subagent disagreed" appended; that pushes the reconciliation onto the
  reader.
- Where you and the refuter disagree and reading the code does not settle it, the finding is **not
  proven**. Present it as a question to the author, not as a defect.
- A downward severity revision is a legitimate reconciliation of `SURVIVES` plus mitigating refuter
  evidence. It is not the same as `REFUTED`, and it is why the verdict set has no `OVERSTATED`.
- Label what you are asserting: Verified, Inferred, or Assumed, per `epistemic-honesty`.
- Re-query `headRefOid` once more before presenting. Staged comments carry line numbers at the
  pinned SHA, so a HEAD move you never detected puts them on the wrong lines.

Report the pass as a table so the subtraction is visible, one row per Phase 1 candidate. A candidate
with no Phase 2 verdict is **unadjudicated**, not `SURVIVES`: re-dispatch it, or record it as
unadjudicated and say so. Silent drops are the predicted failure of a batched refuter, so a blank
cell is a result, not an absence.

| Finding | Phase 1 | Phase 2 | Action |
| --- | --- | --- | --- |
| `src/foo.ts:42` off-by-one on the page boundary | kept, should-fix | UNDERSTATED | Raised to blocking, staged |
| `src/bar.ts:10` unused import | dismissed, nit | REFUTED | Dropped |
| `src/baz.ts:88` missing null guard | dismissed, nit | REINSTATED | Staged as should-fix |

State the counts: candidates in, findings out. A pass that subtracts nothing and adds nothing is
worth reporting as such.

---

## Mode boundaries

This skill writes nothing to GitHub in either mode. It ends with a validated finding set and hands
off.

**`peer`.** Surviving findings go to `/pr-review-batching` for staging as pending-review drafts;
the user submits. Never auto-fix, never reply-accept, never merge someone else's PR.

**`self`.** Surviving findings become work: regression test first, then fix, per the global TDD and
Definition of Done conventions. Thread replies and resolution follow the global PR Review
Conventions; note that thread replies publish immediately and cannot be staged
(`/pr-review-batching` Operation 3). Merge is out of scope for this skill.

Fixing anything invalidates the pass. New commits mean a new head SHA, so re-pin and re-run the
**whole** pass against it, both phases, before concluding the PR is clean. Re-running Phase 1 alone
would leave the new candidates unrefuted, which breaks the no-gate rule; scoping the re-run to only
the findings you touched has been observed to miss regressions the fix itself introduced.

This skill does not own convergence. It runs one pass. A caller that loops fix-then-re-pass owns
the round cap and the stopping condition.

---

## Cost and known weaknesses

- **Cost is `1 + ceil(candidates / 10)` subagents**: one for Phase 1b, plus one Phase 2 dispatch per
  batch. Two for a small pass, three at twenty candidates. A fix cycle re-pins and repeats the whole
  pass, so the number multiplies per cycle. Budget accordingly; the no-gate rule is affordable per
  pass, not per PR.
- **Batched refuter attention degrades as the finding count grows.** This is the main known weakness.
  Cap a dispatch at roughly ten candidates and split past that, grouped by file or subsystem, and
  keep a finding and its proposed fix in the same batch. Splitting costs a subagent; say so when you
  do it.
- **A fresh instance isolates context, not priors.** `pr-code-reviewer` carries user-scoped memory,
  so every instance loads the same stored review heuristics before it reads a line of the diff. A
  Phase 2 refuter is therefore primed by the same heuristics that generated the Phase 1 findings it
  is meant to attack, which makes independence between the phases weaker than the fresh-instance
  rule implies.
- **Correlated blind spots survive both phases.** Three reads by the same model family can all miss
  the same thing. This pass raises precision on the findings you have; it is not evidence that the
  diff is clean.
- **The refuter can refute a real bug.** Its default-to-NOT-PROVEN mandate biases it that way on
  purpose. Phase 3 is where you catch that, which is why a `REFUTED` verdict on something you
  independently verified is a signal to look harder, not to drop it.

---

## Notes

- Global conventions (PR Review Conventions, TDD, Definition of Done, commit and dash rules) live in
  the global `CLAUDE.md` and `~/.claude/rules/`. This skill obeys them and does not restate them.
- Related: `/pr-review` (find and format), `/pr-review-batching` (stage, never publish),
  `agents/pr-code-reviewer.md` (the subagent both phases dispatch),
  `config/rules/epistemic-honesty.md` (the rule this derives from).
