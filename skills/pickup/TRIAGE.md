# Triage reference

The reference half of [`/pickup`](SKILL.md): how to classify what a handoff document leaves open, and the shape of every artifact a run produces. `SKILL.md` holds the steps.

Triage is the only gate protecting an unattended run. Everything downstream inherits its verdict, so it is graded on being exhaustive rather than on being fast: every acceptance criterion carries a verification method, and every open question carries a class.

## Classifying an open question

Each open question lands in exactly one class. Work down the list and stop at the first match.

### Hard blockers

Stop the run. These hold in every mode, and `--force` does not reach them.

| Blocker | What it looks like |
| --- | --- |
| Unreadable input | The handoff document, or an issue, PR, or file it depends on, cannot be read. |
| Contradiction | The handoff document and its linked issue disagree about an acceptance criterion. |
| Irreversible or outward-facing | Schema or data migration, public API or contract change, repo visibility, credentials, auth, anything published to an external service. |
| Expensive to reverse | The decision sets a pattern other code will copy, defines a component's public props, or establishes a layout other views inherit. See the reversibility split below. |
| Unverifiable criterion | An acceptance criterion with no stated way to prove it and none inferable. A run cannot claim an unmeasurable criterion is met. |
| Missing access | Credentials absent, a required service down, a repo unreachable. |
| Dirty tree | Uncommitted or untracked changes of unknown origin. `preflight.py` reports this one. |

`preflight.py` settles unreadable input, missing access, and dirty tree mechanically. The rest are yours to judge, and they are the reason triage is a reading task rather than a script.

### Judgment calls

Decide, record, and continue. Build the reversible way: when options differ in cost to change later, take the cheaper one to undo.

Typical: internal naming, file placement, whether to extract a helper, test structure and granularity, and anything where the options converge on identical user-visible behavior.

Each judgment call earns two records: a row in the Decisions Log, and a `:notebook:` inline comment on the pull request at the line where the decision is visible in the diff. The inline comment is what turns an abstract fork into something reviewable against real code.

### The reversibility split

User-visible divergence alone does not decide the class. Cost to reverse does.

| Cost to reverse | Example | Class |
| --- | --- | --- |
| Cheap | Toast against inline warning, empty-state wording, a control disabled against hidden | Judgment call |
| Expensive | Component prop shape, a layout other views inherit, a pattern the rest of the code will copy | Hard blocker |

## Recommending a mode

Count the user-visible judgment calls after classification, and note whether they cluster on one surface.

| Signal | Recommended mode |
| --- | --- |
| Fewer than 3 user-visible judgment calls, none clustered | `afk` |
| 3 or more, or 2 on the same surface | `hitl` |

Three individually cheap forks in one component means the run would be designing that component rather than implementing a specification. The threshold is a starting default, deliberately visible here so it can be corrected once real runs show where it sits wrong.

When the recommended mode is stricter than the requested mode, the run halts with a mode mismatch and names the forks that caused it. `--force` proceeds anyway. The asymmetry is the point: a blocker means the run cannot know something, while a mismatch means the human probably wants to be present. Only the second is the human's to overrule.

## Acceptance criteria

Every criterion gets a row before any implementation starts, with its verification method fixed while the work still looks easy. Setting the standard up front is what keeps it from sliding once the work turns out to be hard.

| # | Acceptance criterion | Verification method | Evidence |
| --- | --- | --- | --- |
| 1 | Card reflows below 480px | Unit test on the breakpoint hook | `FeatureCard.test.tsx:44` |
| 2 | Warning sits above the fold | Visual | `UNVERIFIED - visual confirmation required` |

Verification methods, in descending preference:

1. **Automated** - a test, a type, a lint rule. Preferred wherever a criterion admits it.
2. **Observed** - the app driven for real, with a screenshot attached. Reach for this only when the app is already running and reachable; on any failure, fall back to the next tier rather than retrying.
3. **Visual** - `UNVERIFIED - visual confirmation required`. An honest gap, listed in the pull request so the human knows exactly what to look at.

A criterion proven only by tier 3 stays unverified in the summary. Reporting it as met would make the run's account of itself worthless, which costs far more than the gap does.

## Artifacts

### Triage file

Written beside the handoff document as `<handoff-basename>.triage.md` before anything else happens, and never rewritten. When that directory is not writable, it goes to the session scratchpad and the run prints the path. This is the one artifact whose value survives a run that never reaches a pull request.

```markdown
# Triage: <handoff document name>

- Mode requested / recommended: afk / afk
- Preflight: clear (exit 0)
- Branch: feat/123-feature-card-layout

## Acceptance criteria
<the table above, Evidence column empty>

## Open questions
| Question | Class | Resolution |
| --- | --- | --- |
| Warning placement | Judgment call (cheap) | Inline; toast is the reversible alternative |

## Blockers
None.
```

### Pull request description

The canonical status surface, updated at every phase boundary. It carries the acceptance criteria table with evidence filled in, the Decisions Log, the unverified list, and anything left outstanding. It also cites the handoff document's filename, which is how a later run finds this one and resumes instead of starting over.

```markdown
Picked up from `handoff-featurecard-layout.md`. Closes #123.

## Acceptance criteria
<table, Evidence column filled>

## Decisions log
| Decision | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Warning placement | Inline | Toast | Inline keeps it beside the field it describes; both are one-line changes |

## Unverified
- AC 2: warning above the fold. Visual confirmation required.

## Outstanding
None.
```

An empty section reads `None.` rather than being dropped, so a reader can tell an empty list from a forgotten one.

### Out-of-scope findings

A review finding that is real but reaches past the handoff document's acceptance criteria goes in `Outstanding` and, when it warrants one, becomes a follow-up issue. Widening a pull request beyond its stated criteria is how an unattended run turns a reviewable change into one nobody can review.
