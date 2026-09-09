#!/usr/bin/env python3
"""Report Copilot's loop-terminating signals for one PR.

Usage: copilot-signals.py <owner> <repo> <pr-number>

Answers the two signals that decide whether the bot loop terminates, and prints
the corroborating detail for the rest.

Exit status is the three-state `landed? + suppressed?` result:

    0  clean            review at head, no inline comments, nothing suppressed
    1  triage-required  review at head withheld or posted findings
    2  not-applicable   no review at head; re-request, or wait if one is pending
    3  error            the query or the arguments failed; no verdict

`landed?` and `suppressed?` cannot be answered independently: with no review at
head there is nothing to suppress, so a head-scoped suppressed check reports the
same zero for "clean" and for "never reviewed". Exit 2 keeps them distinct.

Inline comments fold into exit 1 alongside suppressed ones so that exit 0 is safe
to read as "terminate". Both need the same loop action; the printout separates
them.

Known bound: the query reads the newest 50 reviews. Each thread reply posted over
REST adds an author-authored review artifact, so a PR that accumulated more than
50 of them after its head review would push that review out of the window and
report not-applicable. Reaching it takes 50-plus replies with no push in between,
roughly ten times anything measured, and the loop's round cap bounds the outcome
to a wrong report rather than a hang.
"""
import json
import re
import subprocess
import sys

CLEAN, TRIAGE_REQUIRED, NOT_APPLICABLE, ERROR = 0, 1, 2, 3

QUERY = """
query($owner:String!, $repo:String!, $number:Int!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      headRefOid
      reviewRequests(first:20) {
        nodes { requestedReviewer { __typename ... on Bot { login } ... on User { login } } }
      }
      reviews(last:50) {
        nodes {
          author { __typename login }
          submittedAt
          commit { oid }
          comments { totalCount }
          body
        }
      }
    }
  }
}
"""

# Copilot's login differs by surface: `copilot-pull-request-reviewer` in GraphQL,
# `copilot-pull-request-reviewer[bot]` in REST, and plain `Copilot` in the
# re-request response. A filter built by equality against any one of them
# silently never matches, which presents as a review that never lands.
COPILOT = re.compile(r"copilot", re.IGNORECASE)
# Copilot marks withheld findings with a labelled, parenthesised count, but it
# has moved that label between surfaces. It has been the <summary> text
# ("Suppressed comments (N)", "Comments suppressed due to low confidence (N)")
# and, more recently, a heading inside a generic "<summary>Review details</summary>"
# block. Match the label plus its count anywhere in the <details> block, not only
# in the <summary>, or the newer layout parses as "no suppressed block", returns
# CLEAN, and the loop terminates on findings it never read.
#
# The label is matched tightly: the "suppressed comments" / "comments suppressed"
# phrase adjacent to a parenthesised count, never a bare /suppress/. Copilot's
# per-file overview restates each changed file's description, so a PR that is
# *about* suppressing something (e.g. a global error alert) puts the word
# "suppress" in an otherwise clean block; a loose match fires on it. Expect the
# phrasing to drift again, so the no-count variant still flags an unparsable
# label as undeclared rather than skipping it.
SUPPRESSED_LABEL = re.compile(
    r"(?:comments?\s+suppressed|suppressed\s+comments?)[^\n(]*\((\d+)\)",
    re.IGNORECASE,
)
SUPPRESSED_LABEL_NO_COUNT = re.compile(
    r"comments?\s+suppressed|suppressed\s+comments?", re.IGNORECASE
)
# The <details> container is drift-hardened for the same reason. Attributes
# (<details open>) or different casing would otherwise parse as "no block", which
# returns CLEAN on withheld findings. The floor of matching HTML with a regex is a
# quoted attribute containing ">"; not worth chasing, and it fails toward CLEAN,
# so the count mismatch below is what catches it.
#
# Deliberately NOT here: a body-level backstop treating /suppress/i anywhere in
# the body as triage. Copilot's overview table restates each changed file's
# description, so on a PR that mentions suppression the phrase appears in a
# genuinely clean review body. That backstop was measured firing on this repo's
# own clean rounds, which is a loop with no fixed point: worse than the early
# termination it would be trying to prevent. Scoping the label to a <details>
# block and requiring the tight phrase plus count is what keeps a
# "suppress"-mentioning PR from self-triaging.
DETAILS_BLOCK = re.compile(
    r"<details[^>]*>\s*<summary[^>]*>(?P<summary>.*?)</summary>(?P<inner>.*?)</details>",
    re.DOTALL | re.IGNORECASE,
)
# Inside the block each real finding is a bold file path ("**path/to/file.ext**"
# or "**path/to/file.ext:line**"). Requiring a dotted extension separates the
# findings from the block's own bold metadata rows ("**Files reviewed:**",
# "**Previously missed (N)**"), which share the bold markup but are not paths.
FINDING = re.compile(
    r"\*\*(?P<file>[^\s*]+\.[A-Za-z0-9]+(?::\d+)?)\*\*\s*(?P<text>.*?)(?=\n\s*\*\*|\Z)",
    re.DOTALL,
)


def parse_suppressed(body):
    """Return (declared_count, [(file, text), ...], [summary_labels], undeclared).

    `undeclared` is True when any suppressed block declared no parsable count.
    It is tracked separately from the running total because summing across
    blocks would otherwise erase it: an undeclared block followed by one
    declaring (0) collapses to a count of 0, and silent-zero is the failure this
    whole signal exists to prevent.
    """
    count = None
    findings = []
    labels = []
    undeclared = False
    for block in DETAILS_BLOCK.finditer(body):
        # The label may live in the <summary> (older layout) or in the block body
        # (the "Review details" layout), so search the whole block, not the summary.
        text = block.group(0)
        with_count = SUPPRESSED_LABEL.search(text)
        no_count = SUPPRESSED_LABEL_NO_COUNT.search(text)
        if with_count:
            labels.append(" ".join(with_count.group(0).split()))
            count = (count or 0) + int(with_count.group(1))
        elif no_count:
            labels.append(" ".join(no_count.group(0).split()))
            undeclared = True
        else:
            continue
        for finding in FINDING.finditer(block.group("inner")):
            finding_text = " ".join(finding.group("text").split())
            if finding_text:
                findings.append((finding.group("file").strip(), finding_text))
    return count, findings, labels, undeclared


def fetch(owner, repo, number):
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={QUERY}",
         "-f", f"owner={owner}", "-f", f"repo={repo}", "-F", f"number={number}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh api graphql failed")
    payload = json.loads(result.stdout)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"]))
    repository = (payload.get("data") or {}).get("repository")
    if repository is None:
        # GitHub returns NOT_FOUND in `errors` for a missing or unreadable repo,
        # so this is caught above in practice. The guard exists because the exit
        # status is the interface: without it the message is a bare "'NoneType'
        # object is not subscriptable", which says nothing about what to fix.
        raise RuntimeError(f"cannot read {owner}/{repo}: no such repository, or no access")
    return repository["pullRequest"]


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip(), file=sys.stderr)
        return ERROR
    try:
        # The query declares number as Int!, so coerce here rather than letting a
        # bad argument surface as a GraphQL type error from two layers down.
        number = int(sys.argv[3])
    except ValueError:
        print(f"ERROR: pr-number must be an integer, got {sys.argv[3]!r}", file=sys.stderr)
        return ERROR
    pr = fetch(sys.argv[1], sys.argv[2], number)
    if pr is None:
        raise RuntimeError(f"no pull request {number} in {sys.argv[1]}/{sys.argv[2]}")

    head = pr["headRefOid"]
    print(f"head {head}")

    # GraphQL is the only surface that shows a pending Copilot request. Both
    # `gh pr view --json reviewRequests` and REST /requested_reviewers return
    # empty while one is outstanding, so an adapter reading either double-requests.
    # Same two conditions as the review filter below. A human collaborator whose
    # login contains "copilot" would otherwise read as a pending bot request,
    # which parks the loop in wait instead of re-requesting.
    pending = [
        reviewer["login"]
        for reviewer in (node["requestedReviewer"] or {} for node in pr["reviewRequests"]["nodes"])
        if reviewer.get("__typename") == "Bot" and COPILOT.search(reviewer.get("login") or "")
    ]
    print(f"pending {pending if pending else 'none'}")

    at_head = None
    at_head_submitted = ""
    for review in pr["reviews"]["nodes"]:
        # Our own `:zap:` thread replies create author-authored COMMENTED review
        # artifacts with empty bodies. Only Copilot's reviews are verdicts.
        #
        # Two independent conditions. Requiring __typename Bot excludes a human
        # collaborator whose login happens to contain "copilot", and the login
        # match stays a loose substring on purpose: the bot's login differs
        # across API surfaces, and anchoring it would trade a false positive
        # that needs a hostile-named collaborator for a false negative on any
        # future surface, which presents as a review that never lands.
        author = review["author"] or {}
        if author.get("__typename") != "Bot":
            continue
        if not COPILOT.search(author.get("login") or ""):
            continue
        oid = (review["commit"] or {}).get("oid")
        count, findings, labels, undeclared = parse_suppressed(review["body"] or "")
        inline = review["comments"]["totalCount"]
        where = "AT HEAD" if oid == head else f"at {oid[:7] if oid else 'unknown'}"
        if not labels:
            shown = "none"
        elif undeclared and count is None:
            shown = f"UNDECLARED via {labels}"
        elif undeclared:
            shown = f"{count} declared plus an undeclared block via {labels}"
        else:
            shown = f"{count} via {labels}"
        print(f"\n=== review {review['submittedAt']} {where} "
              f"inline={inline} suppressed={shown}")
        for path, text in findings:
            print(f"  - {path}: {text[:300]}")
        # Only meaningful when every block declared a count; with a mixed body
        # `count` sums the declared blocks while `findings` spans all of them,
        # so the comparison would warn spuriously.
        if not undeclared and count is not None and len(findings) != count:
            print(f"  WARNING: declared {count}, parsed {len(findings)}; "
                  f"read the review body directly")
        # A head can carry more than one review (re-requested without pushing), and
        # PullRequest.reviews takes no orderBy argument, so the connection's order is
        # not a contract. Decide on the most recently submitted one explicitly.
        submitted = review["submittedAt"] or ""
        if oid == head and submitted >= at_head_submitted:
            at_head = (inline, count, labels, len(findings), undeclared)
            at_head_submitted = submitted

    # Only the review at head decides the loop. A historical review's suppressed
    # block was already triaged and fixed, but it stays in the PR forever, so a
    # detector scanning every review never reaches clean. That failure presents
    # as progress, which makes it worse than terminating early.
    if at_head is None:
        print("\nNOT APPLICABLE: no Copilot review at head. Copilot does not "
              "re-review on push, so this is silent abandonment, not clean. "
              "Re-request, or wait if one is already pending.")
        return NOT_APPLICABLE
    inline, count, labels, parsed, undeclared = at_head
    if not labels:
        withheld = "no suppressed block"
    elif undeclared:
        withheld = "a suppressed block declaring no parsable count"
    elif parsed != count:
        withheld = f"a suppressed block declaring {count} but carrying {parsed}"
    else:
        withheld = f"{count} suppressed"
    # Parsed findings and an undeclared count each decide alongside the declared
    # total, never under it. A block that declares (0) while carrying findings is
    # a silent zero, which is the failure this signal exists to prevent, and it is
    # the assertive kind: the mismatch means the body format moved and the parse
    # is no longer trustworthy in either direction.
    if inline or parsed or undeclared or (labels and (count is None or count > 0)):
        print(f"\nTRIAGE REQUIRED: {inline} inline, {withheld}.")
        return TRIAGE_REQUIRED
    print("\nCLEAN: a review at head posted nothing and withheld nothing.")
    return CLEAN


if __name__ == "__main__":
    # Every unexpected failure has to land on ERROR. An uncaught exception would
    # exit 1, which is TRIAGE_REQUIRED, so a crash would read to the loop as a
    # verdict. Reporting no verdict is the one thing this script must get right.
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(ERROR)
