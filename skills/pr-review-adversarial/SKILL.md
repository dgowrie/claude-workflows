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

Run the whole pass when the cost of shipping a wrong finding or an unsafe fix exceeds two
subagents: correctness, security, data safety, API contracts, migrations, anything you are about
to implement rather than merely mention, and any review of a diff you authored yourself.

Skip it for a diff whose entire risk surface is prose or formatting.

**There is no gate inside the pass.** Once you are running it, every candidate reaches Phase 2,
including the ones you already decided were cosmetic. That is deliberate: the pattern's biggest
observed win was a refuter upgrading a finding that had been called cosmetic into a real
off-by-one bug, which any severity gate would have excluded. With one batched refuter the marginal
cost of carrying a nit through is close to zero.

---

## Inputs

| Input | Values | Default |
| --- | --- | --- |
| `pr` | PR URL or number; or a local diff surface when no PR exists | required |
| `mode` | `peer` (someone else's PR) or `self` (yours) | inferred from PR author, confirm if ambiguous |
| `findings` | An existing candidate set to validate | empty; Phase 1 produces one |

When `findings` is supplied (for example `/pr-review` just ran and produced them), still run Phase
1b, the independent subagent. A candidate set you already hold is exactly the input Phase 1b is
meant to be uncontaminated by.

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
- If HEAD moves before the pass finishes, the pass is invalid. Re-pin and redo Phase 1 against the
  new SHA rather than reconciling across two trees.
- Use `dangerouslyDisableSandbox: true` for `gh` (corporate proxy TLS).

---

## Phase 1: additive, attack the CODE

Two independent reads of the same diff. The output is a union, not a consensus.

### 1a. Your own skeptical pass

Follow `/pr-review` Steps 3 through 7 (repo context, PR type, focus areas, bot cross-check,
verify-before-flagging). Bot threads count as candidate findings here, including resolved ones;
a silent dismissal is a candidate like any other.

### 1b. One independent fresh-context reviewer

Dispatch a single `pr-code-reviewer` subagent at the same diff.

- **Do not pass it your findings.** Anchoring it on your candidates is the whole failure this
  phase is built to avoid. Give it the PR ref, the head SHA, and the instruction to review
  independently.
- In `self` mode, do not tell it the diff is yours.

### Union and classify

Merge both result sets. Deduplicate by (path, line, claim), not by wording.

Agreement between 1a and 1b is **weak** evidence. Both reads share a model, a prompt lineage, and
the same diff; correlated priors make correlated mistakes. Note corroboration, do not treat it as
verification.

Split the union into two lists that both carry into Phase 2:

- `kept[]` - candidates you would flag. Each carries: id, `path:line`, claim, evidence, proposed
  fix (if any), severity.
- `dismissed[]` - candidates you considered and rejected, cosmetic nits included. Each carries the
  same fields plus **the reason you dismissed it**. Without the reason the refuter has nothing to
  attack.

---

## Phase 2: subtractive, attack the FINDINGS

One `pr-code-reviewer`, batched over the whole union.

**It must be a new instance.** Spawn a fresh agent; do not continue the Phase 1b agent via
`SendMessage`. An agent that authored a finding will confirm it, which produces a verdict with no
information in it.

Its mandate:

- Refute every entry in `kept[]` and every entry in `dismissed[]`.
- Attack the **proposed fix** as a separate target from the claim. A correct finding with an unsafe
  fix is the expensive case: one observed run flagged that a proposed NUL-byte (U+0000) key
  separator would be rejected by Postgres `text` columns downstream, where the finding itself was
  fine.
- Attack each dismissal rationale in `dismissed[]` on its own terms.
- **Default to NOT PROVEN.** Uncertainty resolves against the finding, not for it.
- Cite evidence read at the pinned SHA. "Looks like" is not evidence.

### Verdicts

| Verdict | Meaning | Action |
| --- | --- | --- |
| `REFUTED` | The claim does not hold at the pinned SHA | Drop it. Do not present it hedged |
| `SURVIVES` | The attack failed | Keep as stated |
| `UNDERSTATED` | Real, and worse than stated (severity, blast radius, or root cause) | Upgrade before presenting |
| `REINSTATED` | A `dismissed[]` entry the refuter shows was wrongly dismissed | Promote into `kept[]` at the refuter's severity |

`UNDERSTATED` and `REINSTATED` are why the pass is worth running. A refuter that only ever returns
`REFUTED` and `SURVIVES` is being used as a rubber stamp.

Required per-finding output: `{id, verdict, evidence, revised_fix?}`.

---

## Phase 3: reconcile

The refuter's verdicts are input to your judgment, not a substitute for it. It can be wrong in both
directions.

- Address every verdict: verify it, revise the finding, or record it as an open risk. Never present
  a finding with "though a subagent disagreed" appended; that pushes the reconciliation onto the
  reader.
- Where you and the refuter disagree and reading the code does not settle it, the finding is **not
  proven**. Present it as a question to the author, not as a defect.
- Label what you are asserting: Verified, Inferred, or Assumed, per `epistemic-honesty`.

Report the pass as a table so the subtraction is visible:

| Finding | Phase 1 | Phase 2 | Action |
| --- | --- | --- | --- |
| `src/foo.ts:42` off-by-one on the page boundary | kept, warning | UNDERSTATED | Raised to bug, staged |
| `src/bar.ts:10` unused import | dismissed, cosmetic | REFUTED | Dropped |
| `src/baz.ts:88` missing null guard | dismissed, cosmetic | REINSTATED | Staged as bug |

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

Fixing anything invalidates the pass. New commits mean a new head SHA, so re-pin and re-run Phase 1
against it before concluding the PR is clean.

---

## Cost and known weaknesses

- **Cost is fixed at 2 subagents per pass**, independent of finding count. That is what makes the
  no-gate rule affordable.
- **Batched refuter attention degrades as the finding count grows.** This is the main known weakness.
  Past roughly ten candidates, split Phase 2 into two dispatches grouped by file or subsystem, and
  keep a finding and its proposed fix in the same batch. Splitting costs a subagent; say so when you
  do it.
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
