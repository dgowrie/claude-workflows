# Silent Zeros: Make Failure Representable

A **silent zero** is a failure that renders as a benign empty result: an empty list, an empty string, a zero, a `False`, a `None`. The call failed, the return value says nothing happened, and nothing is indistinguishable from fine.

This is the single most common defect shape in gate and precondition code, and it is nearly invisible in review because the code reads as correct. It reached production-shaped code nine times in one PR, in a script whose entire stated purpose was to avoid it, written by an author who had already fixed the same bug twice in adjacent functions.

## The check

For every branch that returns a value, ask two questions:

1. **Can a failure produce this same value?**
2. **If so, can the caller tell the two apart?**

If the answer is no, that is the bug, whatever the surrounding code looks like. The fix is not a better error message. It is to **make the failure representable in the return type**.

## What it looks like

| The call | Returns on failure | Caller reads it as |
| --- | --- | --- |
| `git status --porcelain` | empty output | the tree is clean |
| `gh pr list` | `[]` | there are no open PRs |
| Reading an owners file | `[]` | nobody owns this code |
| A paginated listing | a full page | that is all of them |
| `rev-parse --abbrev-ref HEAD` | `"HEAD"` | a branch named HEAD |
| Any subprocess with a bad `cwd` | non-zero | the tool is unauthenticated |

Note the last row: a failure in one dimension gets attributed to an unrelated cause, which sends the reader after the wrong problem and is worse than no answer.

## The fixes, in order of preference

1. **Widen the return type** so failure has its own value. `None` for "could not look" against `[]` for "looked, found nothing". A three-state string against a boolean. A separate `ok` or `readable` or `checked` flag beside the data.
2. **Keep the return code.** Discarding it with `_` is how most of these start. If a command's exit status is the only signal that its empty output is meaningless, that status is data.
3. **Detect saturation, not just emptiness.** A full page means the window may have truncated the answer.
4. **Fail closed.** Where a gate cannot know, it refuses and names the question it could not answer. A gate that fails open is worse than no gate, because it is trusted.

## Why tests do not catch it

Happy-path tests and manual smoke runs exercise the branch where things work. A silent zero lives in the branch where they do not, and that branch is usually the one no fixture constructs.

- **Force the failure in a test.** Make the file undecodable, point `cwd` at nothing, stub the command to a non-zero exit, fill the page to the limit. If no test makes the call fail, the failure path is unverified regardless of coverage numbers.
- **Pin the environment the branch depends on.** An encoding, a locale, a git version. A test that passes because CI happens to be UTF-8 is asserting a property of the runner, not of the code.
- **A check moved into a script is reliable, not correct.** Putting a precondition in code rather than prose makes it run every time. It does nothing to make it right, and the confidence it produces is the reason nobody looks again.

## When this applies

Any code where a caller acts on the answer without a human in between: preconditions, gates, health checks, resume and idempotency detection, ownership and permission lookups, anything an unattended run consults before doing something outward-facing.

Related: [`epistemic-honesty`](epistemic-honesty.md), whose "treating absence as evidence" failure mode is this rule's reasoning counterpart. Absence of a signal means look harder, in code as in analysis.
