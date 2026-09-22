---
name: author-review-guidance
description: >
  Post review-guidance comments on your own PRs as a single review submission: a walkthrough as
  the review body, plus inline `:notebook:` comments threaded below for anything a reviewer
  would predictably ask "why this way?" about. Stage via the pr-review-batching skill. Trigger
  phrases: "add review guidance to my PR", "walk reviewers through this PR", "annotate my own
  PR for reviewers", "post a walkthrough on this PR", or explicit `/author-review-guidance`.
---

# Author Review Guidance

When asked, post review-guidance comments on your own PRs as a **single review submission**:
walkthrough as review body, inline comments threaded below.

**Walkthrough** (review body):
- One-paragraph summary of what changed and why.
- Ordered file list in suggested reading order: file path, what changed, why that order.
- Call out what reviewers should skip (mechanical renames, generated code).

**Inline comments** (on specific diff lines):
- Prefix with :notebook: to distinguish from review feedback.
- Add for: dense logic, intentional tradeoffs, subtle constraints, anything where "why this way?"
  is predictable.
- Skip for: obvious changes, anything the walkthrough already covers.
- Flag risk. Keep to 1-2 sentences. If it needs more, the code needs a real comment.

**Mechanics:** Stage via the `pr-review-batching` skill. Don't duplicate the PR description or
commit messages; reference them.
