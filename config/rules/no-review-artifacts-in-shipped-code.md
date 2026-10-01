# No Review/Process Artifacts in Shipped Code

Review-loop and planning artifacts must never leak into committed code. This has
recurred: finding labels ended up in code comments and test names, meaningless to
anyone who did not watch the review, and cleaning them up after approval costs a
commit that can invalidate that approval.

## What counts as an artifact (do not commit these)

- **Review-loop finding labels**: `F1`, `F2`, `C3`, `D1`, etc. - the ids I assign to
  findings during `/pr-review-adversarial`, `/pr-review-bot-loop`, or ad-hoc triage.
- **Reviewer/process names**: "Copilot", "the refuter", "the adversarial pass",
  "bot-loop round", "suppressed finding", "Phase 2".
- **Personal decomposition jargon**: "piece 1 / piece 2", "workstream A", "slice 3" -
  my private breakdown of a task, not a shared vocabulary.

Issue and PR numbers (`#1363`, `PR #1364`) are NOT artifacts - they resolve to something
real and are fine to reference.

## The test

Would a reader who never saw my review or planning process understand this token? If its
only meaning lives inside my workflow, it does not belong in the artifact. Describe the
actual behavior or reason instead:

- Test name: `it('resets to page 1 when the filter changes')`, never `'... (F2)'`.
- Comment: "pagination-under-filter is covered by the RTL tests", never "(F1/F2) covered
  by the RTL tests"; or just delete the comment if the label was the only content.

## Where this applies

Committed code, code comments, and test `describe`/`it` names, first and foremost. Also
commit messages and outward PR/issue bodies: describe the change and cite issue/PR
numbers, not private finding ids. (A `:zap:`/`:thought_balloon:` reply *on a review
thread* may name the finding being answered - that is review-surface, not shipped code.)

## When to check

Self-check before staging/committing, and before writing any outward PR or issue body -
especially when a review loop preceded the commit, which is exactly when these labels are
top of mind. Grep the staged diff for `\bF[0-9]\b`, `\bC[0-9]\b`, `\bpiece [0-9]`,
`adversarial`, `suppressed`, `refuter`, `bot-loop`. Catching it pre-commit is the whole
point: a fix after review means an extra commit and a re-review.

Related: `self-correction-loop.md` (this rule was created from a correction).
