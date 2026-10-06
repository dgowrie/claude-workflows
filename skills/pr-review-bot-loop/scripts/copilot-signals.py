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

A `ccr-overview-vN` body can carry a finding in neither place: in the headline
verdict or its sentence, in a "Review findings" list, or in a vote-tagged mention
in the per-file table. Those fold into exit 1 too and print as `body_only=N` and
`headline="..."`. Only the known-clean verdict, with nothing else in the body,
stays clean; an unknown verdict, an unreadable layout, or a marker version other
than the verified one is triage-required.

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


# The overview layout (`<!-- ccr-overview-v2 -->`) reports findings in three places
# that are neither an inline comment nor a suppressed block: the headline verdict
# and its sentence, a "Review findings" bullet list, and vote-tagged mentions in
# the per-file table. Each was observed reading CLEAN with a real concern in it,
# including under a green verdict, so the parse fails closed: only a verdict on the
# allow-list, with nothing else in the body, is clean. The allow-list holds the one
# verdict observed on a genuinely clean review; any other text is triage-required
# until a second clean sample is captured.
OVERVIEW_MARKER = re.compile(r"<!--\s*ccr-overview-(?P<version>v\d+)\s*-->")
VERIFIED_OVERVIEW_VERSION = "v2"
CLEAN_VERDICTS = {"approval recommended"}
VERDICT_HEADING = re.compile(r"^###[ \t]+(?P<heading>.+?)[ \t]*$", re.MULTILINE)
# A sentence under a clean verdict that still names something outstanding. Tight
# on purpose: "remaining" is common in clean prose ("no remaining issues"), so only
# "remain(s)" counts, and the list is a heuristic that fails toward triage.
#
# A concern word is cancelled by a negator in its own clause: "No minor issues
# remain." holds three of them and is the opposite of a concern, and flagging it
# keeps a genuinely clean review dirty forever. Clauses split on punctuation and on
# the words that turn a sentence back to a positive ("but", "only", "other than"),
# so "No blocking issues, but a nit remains." still names something outstanding.
#
# "and" / "or" are the hard case. Negation is shared across them in "No minor or
# blocking issues remain." and not in "No blocking issues were identified and a
# minor nit remains.", and the second is the fail-open direction. A coordinated
# segment starts a new clause when it opens with a determiner, quantifier, number
# or pronoun (it has its own subject, so it needs its own negator); any other
# opening continues the previous clause and inherits its negation. A leftover
# phrased without a determiner ("and minor nit remains") is the miss this leaves.
CONCERN_PROSE = re.compile(r"\bnits?\b|\bminor\b|\bremains?\b|\bconsider\b", re.IGNORECASE)
#
# A completed resolution cancels a concern word the same way a negator does: "The
# minor nit was fixed." names nothing outstanding. Only a COMPLETED one does, though.
# "was not fixed", "still needs to be fixed" and "should be addressed" carry the same
# resolution word and state the opposite, so they are checked first and are
# outstanding whatever else the clause holds. "unresolved" matches none of these,
# since \bresolved needs a word boundary before it.
RESOLUTION = r"(?:resolved|fixed|addressed|handled|corrected)\b"
NEGATOR = re.compile(r"\b(?:no|not|none|nothing|without|never|neither|nor)\b|n't", re.IGNORECASE)
COMPLETED = re.compile(r"\b(?:was|were|been|is|are|now|already)\s+" + RESOLUTION, re.IGNORECASE)
# The negation here belongs to the resolution, so it is never a shared negator.
NEGATED_RESOLUTION = re.compile(
    r"(?:\b(?:not|never|still|yet)\b|n't)\s+(?:\w+\s+){0,3}?" + RESOLUTION, re.IGNORECASE)
# A modal outstanding unless the clause negates it earlier: "Nothing needs to be
# addressed." is clean, "The issue should be addressed." is not.
PENDING_RESOLUTION = re.compile(
    r"\b(?:needs?|needed|should|must|could|would|might|unless|until|before|to\s+be)\b"
    r"\s+(?:\w+\s+){0,3}?" + RESOLUTION, re.IGNORECASE)
# Sentence dashes break a clause like a comma. Built from code points rather than
# written out, and a bare hyphen only counts when spaced ("well-scoped" must not).
SENTENCE_DASHES = "".join(chr(code) for code in (8211, 8212, 8213))
CLAUSE_BREAK = re.compile(
    r"[;:,.]|[" + SENTENCE_DASHES + r"]|\s-{1,2}\s"
    r"|\b(?:but|however|except|only|though|although|other\s+than|apart\s+from)\b",
    re.IGNORECASE,
)
COORDINATOR = re.compile(r"\b(?:and|or)\b", re.IGNORECASE)
NEW_CLAUSE_OPENING = re.compile(
    r"\s*(?:an?|the|this|that|these|those|some|several|few|many|another|other|any|each|every"
    r"|one|two|three|four|five|six|seven|eight|nine|ten|\d+"
    r"|it|its|there|we|they|i|you|he|she)\b",
    re.IGNORECASE,
)
DECLARED_FINDINGS = re.compile(r"\*\*Findings:\*\*[ \t]*(?:(?P<count>\d+)|(?P<none>none))", re.IGNORECASE)
OPEN_COUNT = re.compile(r"\bOpen\s*\((\d+)\)", re.IGNORECASE)
# A standalone block of findings in code the review says did not change. It has no
# inline thread and no vote tag, so under a green headline it is the only place the
# finding appears.
PREVIOUSLY_MISSED = re.compile(r"\bPreviously\s+missed\s*\((\d+)\)", re.IGNORECASE)
RESOLVED_LABEL = re.compile(r"\bResolved\b", re.IGNORECASE)
REVIEW_FINDINGS_LIST = re.compile(r"\*\*Review findings:\*\*[ \t]*\n(?P<items>(?:[ \t]*[-*][ \t]+.*(?:\n|$))+)")
VOTE_TAG = re.compile(r"\((\d+)\s+votes?\)", re.IGNORECASE)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
HEADLINE_COUNT = re.compile(
    r"\b(?P<count>\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?:\w+\s+){0,3}?"
    r"(?:issues?|findings?|concerns?|problems?|bugs?)\b",
    re.IGNORECASE,
)


class Overview:
    """What an overview-layout body says outside inline comments and suppressed blocks.

    `body_only` is approximate in both directions. Inline comments and `Open (N)`
    account for some findings, but one finding can become several inline comments,
    so the subtraction can hide a body-only finding while inline comments exist;
    and a finding repeated within one section can be counted more than once. The
    verdict depends only on whether it is non-zero, and inline comments already
    require triage, so the case it exists for, zero inline comments, is the one
    where it is tightest.
    """

    def __init__(self, verdict, sentence, declared, open_count, body_only, reasons, warnings):
        self.verdict = verdict
        self.sentence = sentence
        self.declared = declared
        self.open_count = open_count
        self.body_only = body_only
        self.reasons = reasons
        self.warnings = warnings


def names_outstanding(sentence):
    """True when some clause of `sentence` has a concern word and nothing cancelling it."""
    for segment in CLAUSE_BREAK.split(sentence):
        negated = False
        for position, part in enumerate(COORDINATOR.split(segment)):
            if position == 0 or NEW_CLAUSE_OPENING.match(part):
                negated = False
            if NEGATED_RESOLUTION.search(part):
                return True
            pending = PENDING_RESOLUTION.search(part)
            if pending and not (negated or NEGATOR.search(part[:pending.start()])):
                return True
            negated = negated or bool(NEGATOR.search(part) or COMPLETED.search(part))
            if CONCERN_PROSE.search(part) and not negated:
                return True
    return False


def _strip_emoji_prefix(heading):
    return re.sub(r"^[^\w]+", "", heading).strip()


def parse_overview(body, inline):
    """Return an Overview for a `ccr-overview-vN` body, or None for any other body.

    `reasons` is empty only when the headline is on the clean allow-list and
    nothing else in the body carries a finding. Every other outcome, including a
    layout this parser cannot read, carries a reason: a parse that cannot tell is
    triage-required, never clean.
    """
    marker = OVERVIEW_MARKER.search(body)
    if not marker:
        return None
    text = body[marker.end():]
    top_level = DETAILS_BLOCK.sub("", text)
    reasons = []
    warnings = []

    heading = VERDICT_HEADING.search(top_level)
    verdict, sentence = None, ""
    if heading:
        verdict = _strip_emoji_prefix(heading.group("heading"))
        # The sentence is the first paragraph after the heading, unless that
        # paragraph is already the bold metadata rows ("**Review effort:** ...").
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", top_level[heading.end():]) if p.strip()]
        if paragraphs and not paragraphs[0].startswith(("**", "<")):
            sentence = " ".join(paragraphs[0].split())

    declared_match = DECLARED_FINDINGS.search(top_level)
    declared = None
    if declared_match:
        declared = int(declared_match.group("count")) if declared_match.group("count") else 0

    open_count = None
    previously_missed = 0
    counted_blocks = []
    for block in DETAILS_BLOCK.finditer(text):
        summary = block.group("summary")
        missed_match = PREVIOUSLY_MISSED.search(summary)
        if missed_match:
            previously_missed += int(missed_match.group(1))
        open_match = OPEN_COUNT.search(summary)
        if open_match:
            open_count = (open_count or 0) + int(open_match.group(1))
        # Resolved threads keep their vote tags. They were triaged in an earlier
        # round, so counting them keeps every clean round dirty forever.
        if not RESOLVED_LABEL.search(summary):
            counted_blocks.append(block.group(0))
    countable = DETAILS_BLOCK.sub("", text) + "\n" + "\n".join(counted_blocks)

    # The list and the per-file table can restate the same finding, so summing
    # them, or counting every vote tag in the body, counts it twice. Count each
    # section on its own and take the larger: a lower bound on distinct findings
    # that never double-counts across sections and does not assume the list is
    # complete. A finding repeated within the table can still overcount; the
    # verdict depends only on whether the number is non-zero.
    list_match = REVIEW_FINDINGS_LIST.search(countable)
    if list_match:
        list_items = len(re.findall(r"^[ \t]*[-*][ \t]+", list_match.group("items"), re.MULTILINE))
        outside_list = countable[:list_match.start()] + countable[list_match.end():]
    else:
        list_items, outside_list = 0, countable
    body_findings = max(list_items, len(VOTE_TAG.findall(outside_list)))
    body_only = max(0, body_findings - max(open_count or 0, inline)) + previously_missed

    # Parsed best-effort, never trusted: a later version can move findings
    # somewhere this parser does not read, so its headline cannot clear a review.
    if marker.group("version") != VERIFIED_OVERVIEW_VERSION:
        reasons.append(f"overview layout {marker.group('version')} is not the verified "
                       f"{VERIFIED_OVERVIEW_VERSION}")
    if verdict is None:
        reasons.append("an overview body with no parsable headline")
    elif verdict.casefold().rstrip(".!") not in CLEAN_VERDICTS:
        reasons.append(f'headline verdict "{verdict}" is not a known-clean verdict')
    elif names_outstanding(sentence):
        reasons.append("the headline sentence names something outstanding")
    if declared:
        reasons.append(f"declares {declared} finding{'s' if declared != 1 else ''}")
    if open_count:
        reasons.append(f"lists {open_count} open")
    if body_only:
        reasons.append(f"{body_only} body-only finding{'s' if body_only != 1 else ''}")
    # "All three issues were resolved." and "No one found any issues." hold a count
    # word that is not a count of outstanding findings, so a clause with a negator or
    # a completed resolution takes no part in the cross-check. Scoped to the clause
    # holding the count: "Three blocking issues were found, but no nits remain." has
    # a clean clause that must not hide the count in the other.
    for clause in CLAUSE_BREAK.split(sentence):
        count_match = HEADLINE_COUNT.search(clause)
        if not count_match or NEGATOR.search(clause) or COMPLETED.search(clause):
            continue
        said = count_match.group("count").lower()
        said = NUMBER_WORDS.get(said) or int(said)
        # Only a count the body also declares can disagree with it.
        disagreeing = [n for n in (declared, open_count) if n is not None and n != said]
        if disagreeing:
            mismatch = f"headline says {said} but the body declares {disagreeing[0]}"
            reasons.append(mismatch)
            warnings.append(mismatch)
            break
    return Overview(verdict, sentence, declared, open_count, body_only, reasons, warnings)


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
        overview = parse_overview(review["body"] or "", inline)
        where = "AT HEAD" if oid == head else f"at {oid[:7] if oid else 'unknown'}"
        if not labels:
            shown = "none"
        elif undeclared and count is None:
            shown = f"UNDECLARED via {labels}"
        elif undeclared:
            shown = f"{count} declared plus an undeclared block via {labels}"
        else:
            shown = f"{count} via {labels}"
        body_only = "n/a" if overview is None else overview.body_only
        print(f"\n=== review {review['submittedAt']} {where} "
              f"inline={inline} suppressed={shown} body_only={body_only}")
        if overview is not None:
            # A headline-only concern has no thread and no suppressed block, so an
            # exit 1 caused by it alone is unreadable without the sentence.
            if overview.verdict is None:
                print("  headline=UNPARSABLE")
            else:
                headline = f"{overview.verdict}: {overview.sentence}" if overview.sentence else overview.verdict
                print(f'  headline="{headline[:300]}"')
            for warning in overview.warnings:
                print(f"  WARNING: {warning}; the format may have moved, "
                      f"read the review body directly")
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
            at_head = (inline, count, labels, len(findings), undeclared,
                       overview.reasons if overview else [])
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
    inline, count, labels, parsed, undeclared, overview_reasons = at_head
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
    if inline or parsed or undeclared or overview_reasons or (labels and (count is None or count > 0)):
        overview_detail = f"; overview: {'; '.join(overview_reasons)}" if overview_reasons else ""
        print(f"\nTRIAGE REQUIRED: {inline} inline, {withheld}{overview_detail}.")
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
