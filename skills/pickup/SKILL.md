---
name: pickup
description: Run a handoff document through to a reviewed pull request, attended or unattended.
argument-hint: "<handoff-doc-path> [afk|semi|hitl] [--force]"
disable-model-invocation: true
---

# Pickup

The other end of [`/handoff`](../handoff/SKILL.md). `/handoff` compacts a session into a document; `/pickup` takes that document and drives it to a pull request that a human can review.

Read [`TRIAGE.md`](TRIAGE.md) at Phase 0. It carries the classification taxonomies, the mode thresholds, and every artifact format this file refers to.

Run `gh` and `preflight.py` outside the command sandbox. The sandbox cannot reach the credential keyring, so `gh auth status` exits 1 there and a working install reports as unauthenticated.

## Modes

The mode is the second argument, defaulting to `afk`.

| Mode | At triage | Open questions | At phase boundaries |
| --- | --- | --- | --- |
| `afk` | Proceeds | Decided, logged, flagged inline on the PR | Proceeds |
| `semi` | Stops for review | Decided provisionally, batched | Stops with the batch |
| `hitl` | Stops; `/grill-me` until every question is resolved, `/prototype` when a fork needs to be seen before it is chosen | Resolved by the human | Proceeds |

`hitl` is interactive only until triage clears. After that it runs like `afk`.

## Phase 0: Triage

1. Run `scripts/preflight.py --handoff-doc <path> --cwd <repo>` outside the sandbox. Keep the JSON; later phases reuse it.
2. On exit 1, print each blocker with its detail and stop. This holds in every mode, and `--force` does not reach it.
3. Read the handoff document and every issue, PR, and file it references.
4. Build the acceptance criteria table, fixing each criterion's verification method now, while the work still looks easy.
5. Classify every open question against the taxonomies in `TRIAGE.md`. A hard blocker stops the run here, printed the same way as a preflight blocker.
6. Count the user-visible judgment calls and recommend a mode.
7. Write the triage file.
8. Apply the mode gate. When the recommended mode is stricter than the requested one, print the mismatch, name the forks that caused it, and stop unless `--force` is present. Then follow the mode's row in the table above.

Phase 0 is done when every acceptance criterion carries a verification method, every open question carries a class, the triage file exists, and the mode is settled.

## Phase 1: Branch

When preflight reported an existing pull request, this run is a resume: read that PR's description for the state the earlier run reached, and re-enter at the phase its Outstanding section points to.

Otherwise, on the default branch, fetch and branch from `origin/main` as `type/<issue#>-<slug>`, taking the issue from the handoff document and falling back to `type/<slug>` from its title. On a feature branch already, keep it; the handoff most likely came from a session that made it.

Phase 1 is done when the branch is a feature branch and its name has been printed.

## Phase 2: Implement

1. Work criterion by criterion, red first: write the failing test, confirm it fails, then implement to green.
2. Keep commits discrete, mapping to logical units rather than to time spent.
3. Open a **draft** pull request as soon as the first commit exists, citing the handoff document's filename in the body. The description is this run's canonical status surface, and it is also how a later run finds this one; opening it early is what makes a resume possible after the session dies.
4. Update the description at every phase boundary from here on.
5. For each judgment call, build the reversible option, add its Decisions Log row, and leave a `:notebook:` inline comment where the decision shows up in the diff.

Phase 2 is done when every acceptance criterion carries evidence or is explicitly marked unverified.

## Phase 3: Validate

Run the full test suite, the typechecker, and the linter, with lint clean meaning zero warnings in touched files. Lint autofix lands as its own commit. Push, then wait for CI: CI is authoritative, and local green is necessary rather than sufficient.

Phase 3 is done when the suite, typecheck, and lint are green locally and CI is green on the pushed head.

## Phase 4: Review cycle

One cycle is `/pr-review-bot-loop` to a clean pass, then `/pr-review-adversarial`. Fixes from the adversarial pass invalidate the clean bot pass, so a cycle that lands fixes is followed by another cycle.

Route each finding:

| Finding | Action |
| --- | --- |
| Confirmed | Fix, commit, reply `:zap: <hash>` |
| Wrong | Reply `:thought_balloon: <rationale>`, leave the thread open |
| Real but past the acceptance criteria | Record under Outstanding; raise a follow-up issue when it warrants one |

Cap the run at 3 cycles. On exhaustion, stop, leave the pull request as it stands, and write what remains open and why. A run that reports honestly on an unconverged pull request is worth more than one that keeps grinding or declares victory.

Phase 4 is done when a full cycle completes with a clean bot pass and zero new confirmed findings, or when the third cycle ends.

## Phase 5: Hand back

Mark the pull request ready for review. Resolve reviewers by re-running preflight with `--paths` over the changed files and using the CODEOWNERS result, falling back to a reviewer named in the handoff document; when neither yields one, say so rather than guessing at a person. Update the description a final time and print a summary: criteria met, criteria unverified, decisions taken, anything outstanding.

Phase 5 is done when the pull request is ready for review, a reviewer is requested or their absence is stated, and the summary is printed.

## Mandate

Invoking this skill authorizes it, for this one pull request and this run only, to commit, push, publish review replies, and request a reviewer without asking again. This is a deliberate carve-out: the standing convention is to stage review comments for the human to submit, and an unattended run has nobody to ask.

These stay the human's, in every mode: merging, force-pushing, changing repository visibility, and touching any pull request other than the one this run created.

Notify at exactly four moments, so that a notification always means something happened: a triage hard stop, a mode mismatch halt, cycle-cap exhaustion, and successful completion.
