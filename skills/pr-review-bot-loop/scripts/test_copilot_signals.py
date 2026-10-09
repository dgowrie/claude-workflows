#!/usr/bin/env python3
"""Tests for copilot-signals.py.

    python3 -m unittest discover -s skills/pr-review-bot-loop/scripts -v

Offline by default. The live cases need network and an authenticated `gh`, so
they are opt-in:

    SIGNALS_LIVE=1 python3 -m unittest discover -s skills/pr-review-bot-loop/scripts

Both halves matter. The synthetic cases cover states no PR in this repo can
reach, and the live cases are the discipline the skill itself prescribes:
validate the detector against a PR whose answer is already known, across a state
transition rather than at a single point.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("copilot-signals.py")


def load():
    spec = importlib.util.spec_from_file_location("copilot_signals", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signals = load()

HEAD = "a" * 40
OLD = "b" * 40

SUPPRESSED_TWO = (
    "<details><summary>Suppressed comments (2)</summary>\n"
    "**src/a.py** one\n**src/b.py** two\n</details>"
)
SUPPRESSED_ZERO_WITH_FINDINGS = (
    "<details><summary>Suppressed comments (0)</summary>\n"
    "**src/a.py** something real was withheld here\n</details>"
)
SUPPRESSED_EMPTY = "<details><summary>Suppressed comments (0)</summary>\n</details>"
SUPPRESSED_UNDECLARED = (
    "<details><summary>Suppressed comments</summary>\n**src/a.py** x\n</details>"
)
OLD_LABEL = (
    "<details><summary>Comments suppressed due to low confidence (3)</summary>\n"
    "**src/a.py** one\n**src/b.py** two\n**src/c.py** three\n</details>"
)
BENIGN = "<details><summary>Show a summary per file</summary>\n**src/a.py** fine\n</details>"
# The current Copilot layout: a generic "Review details" <summary> with the
# labelled count as a heading inside the block, not in the summary. The
# summary-only gate read this as clean and terminated the loop on the withheld
# finding; this is the regression these cases lock down.
REVIEW_DETAILS_SUPPRESSED = (
    "### Changes recommended\n\n"
    "The tooltip text reads like a total while the metric is a rate series.\n\n"
    "<details>\n<summary>Review details</summary>\n\n"
    "### Suppressed comments (1)\n\n"
    "**Previously missed (1)** - in code that has not changed since the last review.\n\n"
    "**src/components/FeatureCard/index.tsx:35**\n"
    "* The prop comment says space-between but the layout uses marginLeft:auto.\n\n"
    "- **Files reviewed:** 16/16 changed files\n"
    "- **Comments generated:** 1\n"
    "- **Review effort level:** Lite\n"
    "</details>"
)
# A clean review in the same layout whose prose and per-file summary both mention
# "suppress" (the PR is about suppressing an alert) but which withholds nothing.
# The tight label plus <details> scoping must keep this clean, or the loop never
# terminates on a suppress-mentioning PR.
REVIEW_DETAILS_CLEAN_MENTIONS_SUPPRESS = (
    "### Looks good\n\n"
    "This PR makes the background query suppress the global error alert.\n\n"
    "<details>\n<summary>Review details</summary>\n\n"
    "- **Files reviewed:** 16/16 changed files\n"
    "- **Comments generated:** 0\n"
    "</details>\n"
    "<details>\n<summary>Show a summary per file</summary>\n\n"
    "**src/hooks/use-x.ts** Now suppresses the global error alert on failure.\n"
    "</details>"
)

# The `ccr-overview-v2` body layout. Findings can live in the headline, a
# "Review findings" list, or a per-file table cell, none of which is an inline
# comment or a suppressed block, so every shape below read as CLEAN before the
# overview parse existed. The bodies are synthetic: the observed PRs are private.
OVERVIEW_MARKER = "<!-- ccr-overview-v2 -->\n\n## Copilot review overview\n\n"
OVERVIEW_CLEAN = (
    OVERVIEW_MARKER + "### 🟢 Approval recommended\n\n"
    "The changes are fully reviewed, tested, and have no unresolved blocking issues.\n\n"
    "**Review effort:** Lite\n**Findings:** None\n"
)
# A headline-only concern: the one place the finding appears is the sentence.
OVERVIEW_HEADLINE_CONCERN = (
    OVERVIEW_MARKER + "### 🔵 Needs a closer look\n\n"
    "The boundary case in the changed component is not handled.\n\n"
    "**Review effort:** Lite\n**Findings:** None\n\n"
    "<details>\n<summary><strong>What changed in this PR</strong></summary>\n\n"
    "A summary paragraph.\n\n| File | Reviewed changes |\n|---|---|\n"
    "| `src/a.ts` | Reworked the handler. |\n</details>\n"
)
# A green verdict whose sentence still names a leftover nit.
OVERVIEW_CLEAN_VERDICT_WITH_NIT = (
    OVERVIEW_MARKER + "### 🟢 Approval recommended\n\n"
    "No blocking issues were identified; only a minor test naming nit remains.\n\n"
    "**Review effort:** Lite\n**Findings:** None\n"
)
OVERVIEW_REVIEW_FINDINGS_LIST = (
    OVERVIEW_MARKER + "### 🟡 Changes recommended\n\n"
    "A moderate issue affects the handler.\n\n"
    "**Findings:** None\n\n"
    "<details>\n<summary><strong>What changed in this PR</strong></summary>\n\n"
    "**Review findings:**\n"
    "- **Moderate (2 votes):** the handler drops errors.\n"
    "- **Moderate (1 vote):** the retry has no cap.\n\n"
    "A summary paragraph.\n</details>\n"
)
# Finding C has no inline thread and is absent from Open (N); only the per-file
# cell and the headline count betray it.
OVERVIEW_TABLE_ONLY_FINDING = (
    OVERVIEW_MARKER + "### 🟡 Changes recommended\n\n"
    "Three unresolved moderate issues affect two areas.\n\n"
    "**Review effort:** Lite\n**Findings:** 2 moderate\n\n"
    "<details open>\n<summary><strong>Open (2)</strong></summary>\n\n"
    "- moderate [Finding A](#discussion_r1) · New\n"
    "- moderate [Finding B](#discussion_r2) · New\n</details>\n\n"
    "<details>\n<summary><strong>What changed in this PR</strong></summary>\n\n"
    "| File | Summary |\n|---|---|\n"
    "| `src/one.ts` | Change. Moderate issue: Finding B (2 votes). |\n"
    "| `src/two.ts` | Change. Moderate issues: Finding A (2 votes), and Finding C (1 vote). |\n"
    "</details>\n"
)
# A green verdict, but a vote-tagged finding that nothing else accounts for.
OVERVIEW_CLEAN_VERDICT_TABLE_FINDING = (
    OVERVIEW_CLEAN + "\n<details>\n<summary><strong>What changed in this PR</strong></summary>\n\n"
    "| File | Summary |\n|---|---|\n"
    "| `src/one.ts` | Change. Moderate issue: Finding C (1 vote). |\n</details>\n"
)
# Resolved threads keep their vote tags; they were already triaged and must not
# keep a clean round dirty.
OVERVIEW_CLEAN_WITH_RESOLVED = (
    OVERVIEW_CLEAN + "\n<details>\n"
    "<summary><strong>Resolved since last review (1)</strong></summary>\n\n"
    "- moderate [Finding A](#discussion_r1) (2 votes)\n</details>\n"
)
# The same finding in both the "Review findings" list and a per-file cell. It is
# one finding, so it must not read as two.
OVERVIEW_FINDING_IN_LIST_AND_TABLE = (
    OVERVIEW_MARKER + "### 🟡 Changes recommended\n\n"
    "A moderate issue affects the handler.\n\n"
    "**Findings:** None\n\n"
    "<details>\n<summary><strong>What changed in this PR</strong></summary>\n\n"
    "**Review findings:**\n"
    "- **Moderate (2 votes):** the handler drops errors.\n\n"
    "| File | Summary |\n|---|---|\n"
    "| `src/a.ts` | Change. Moderate issue: the handler drops errors (2 votes). |\n"
    "</details>\n"
)
# A finding carried only by a standalone "Previously missed (N)" block: no inline
# thread, no vote tag, and `Findings: None` above it.
PREVIOUSLY_MISSED_BLOCK = (
    "\n<details>\n<summary><strong>Previously missed ({count})</strong></summary>\n\n"
    "In code that hasn't changed since last review\n\n"
    "<details>\n<summary>Avoid counting resolved mentions as findings</summary>\n\n"
    "`src/a.py:208`\n\nThe helper treats every number as a count.\n</details>\n</details>\n"
)
# A resolved section with two nested finding details, each vote-tagged. The outer
# summary says "resolved", so the whole section was triaged in an earlier round. A
# non-greedy details match stops at the first nested `</details>`, iterates the second
# nested finding on its own (its summary has no "resolved"), and leaks its vote tag
# into body_only, so a clean review never terminates.
OVERVIEW_CLEAN_NESTED_RESOLVED = (
    OVERVIEW_CLEAN +
    "\n<details>\n<summary><strong>2 resolved since last review</strong></summary>\n\n"
    "<details>\n<summary>The handler drops errors (2 votes)</summary>\n\na\n</details>\n"
    "<details>\n<summary>The retry has no cap (3 votes)</summary>\n\nb\n</details>\n"
    "</details>\n"
)
OVERVIEW_UNKNOWN_HEADLINE = (
    OVERVIEW_MARKER + "### 🟣 Looks different today\n\nSomething.\n\n**Findings:** None\n"
)
OVERVIEW_NO_HEADLINE = OVERVIEW_MARKER + "**Review effort:** Lite\n**Findings:** None\n"


def review(oid, inline=0, body="", when="2026-01-01T00:00:00Z",
           login="copilot-pull-request-reviewer", typename="Bot"):
    return {"author": {"__typename": typename, "login": login},
            "submittedAt": when, "commit": {"oid": oid},
            "comments": {"totalCount": inline}, "body": body}


def payload(reviews, head=HEAD, pending=()):
    """`pending` takes logins, or (login, __typename) pairs to vary the type."""
    nodes = []
    for entry in pending:
        login, typename = entry if isinstance(entry, tuple) else (entry, "Bot")
        nodes.append({"requestedReviewer": {"__typename": typename, "login": login}})
    return {
        "headRefOid": head,
        "reviewRequests": {"nodes": nodes},
        "reviews": {"nodes": reviews},
    }


class ClassificationTests(unittest.TestCase):
    """Every path that decides whether the loop terminates."""

    def _run(self):
        argv = sys.argv
        sys.argv = ["copilot-signals.py", "owner", "repo", "1"]
        try:
            return signals.main()
        finally:
            sys.argv = argv

    def verdict(self, reviews, head=HEAD, pending=()):
        """Return (exit status, stdout). Patch is scoped, never left behind."""
        out = io.StringIO()
        with mock.patch.object(signals, "fetch",
                               lambda owner, repo, number: payload(reviews, head, pending)):
            with contextlib.redirect_stdout(out):
                code = self._run()
        return code, out.getvalue()

    def assertVerdict(self, reviews, expected, head=HEAD, pending=()):
        code, _ = self.verdict(reviews, head, pending)
        self.assertEqual(code, expected)

    def test_no_review_at_head_is_not_applicable(self):
        """The silent-abandonment trap. Never read this as clean."""
        self.assertVerdict([review(OLD, inline=3, body=SUPPRESSED_TWO)],
                           signals.NOT_APPLICABLE)

    def test_no_reviews_at_all_is_not_applicable(self):
        self.assertVerdict([], signals.NOT_APPLICABLE)

    def test_clean_review_at_head(self):
        self.assertVerdict([review(HEAD)], signals.CLEAN)

    def test_benign_details_block_is_not_suppressed_findings(self):
        self.assertVerdict([review(HEAD, body=BENIGN)], signals.CLEAN)

    def test_block_declaring_zero_and_carrying_none_is_clean(self):
        self.assertVerdict([review(HEAD, body=SUPPRESSED_EMPTY)], signals.CLEAN)

    def test_inline_comments_require_triage(self):
        self.assertVerdict([review(HEAD, inline=2)], signals.TRIAGE_REQUIRED)

    def test_suppressed_findings_require_triage(self):
        """The whole reason the signal exists: zero inline, real findings."""
        self.assertVerdict([review(HEAD, body=SUPPRESSED_TWO)], signals.TRIAGE_REQUIRED)

    def test_block_declaring_zero_while_carrying_findings_requires_triage(self):
        """A silent zero is the assertive form of the failure this signal prevents."""
        self.assertVerdict([review(HEAD, body=SUPPRESSED_ZERO_WITH_FINDINGS)],
                           signals.TRIAGE_REQUIRED)

    def test_undeclared_count_requires_triage(self):
        self.assertVerdict([review(HEAD, body=SUPPRESSED_UNDECLARED)],
                           signals.TRIAGE_REQUIRED)

    def test_older_label_variant_requires_triage(self):
        self.assertVerdict([review(HEAD, body=OLD_LABEL)], signals.TRIAGE_REQUIRED)

    def test_review_details_layout_requires_triage(self):
        """The current layout: the labelled count is a heading inside a generic
        "Review details" block, not the <summary>. The summary-only gate read this
        as clean and terminated the loop on a withheld finding."""
        self.assertVerdict([review(HEAD, body=REVIEW_DETAILS_SUPPRESSED)],
                           signals.TRIAGE_REQUIRED)

    def test_review_details_clean_body_mentioning_suppress_stays_clean(self):
        """The tight label plus <details> scoping keeps a PR that is *about*
        suppressing something clean when it actually withholds nothing."""
        self.assertVerdict([review(HEAD, body=REVIEW_DETAILS_CLEAN_MENTIONS_SUPPRESS)],
                           signals.CLEAN)

    def test_author_review_artifacts_are_not_verdicts(self):
        """Our own :zap: thread replies create empty COMMENTED reviews."""
        self.assertVerdict([review(HEAD, login="dgowrie", body=SUPPRESSED_TWO)],
                           signals.NOT_APPLICABLE)

    def test_latest_review_at_head_wins_when_listed_oldest_first(self):
        self.assertVerdict(
            [review(HEAD, body=SUPPRESSED_TWO, when="2026-01-01T00:00:00Z"),
             review(HEAD, when="2026-01-02T00:00:00Z")], signals.CLEAN)

    def test_latest_review_at_head_wins_when_listed_newest_first(self):
        """PullRequest.reviews takes no orderBy, so neither order may be assumed."""
        self.assertVerdict(
            [review(HEAD, when="2026-01-02T00:00:00Z"),
             review(HEAD, body=SUPPRESSED_TWO, when="2026-01-01T00:00:00Z")],
            signals.CLEAN)

    def test_stale_clean_review_does_not_override_newer_dirty_one(self):
        self.assertVerdict(
            [review(HEAD, when="2026-01-01T00:00:00Z"),
             review(HEAD, body=SUPPRESSED_TWO, when="2026-01-02T00:00:00Z")],
            signals.TRIAGE_REQUIRED)

    def test_container_attributes_do_not_hide_a_suppressed_block(self):
        """<details open> parsed as no block, which returned CLEAN on findings."""
        for markup in (
            '<details open><summary>Suppressed comments (1)</summary>\n'
            '**src/a.py** x\n</details>',
            '<details><summary class="y">Suppressed comments (1)</summary>\n'
            '**src/a.py** x\n</details>',
            '<DETAILS><SUMMARY>Suppressed comments (1)</SUMMARY>\n'
            '**src/a.py** x\n</DETAILS>',
        ):
            with self.subTest(markup=markup[:32]):
                self.assertVerdict([review(HEAD, body=markup)],
                                   signals.TRIAGE_REQUIRED)

    def test_clean_body_mentioning_suppression_stays_clean(self):
        """Copilot's overview table restates file descriptions.

        A body-level /suppress/ backstop was measured firing on this repo's own
        clean rounds, which is a loop with no fixed point.
        """
        body = ("## Pull request overview\n\n| File | Description |\n"
                "| --- | --- |\n| signals.py | detects suppressed findings |\n")
        self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_undeclared_block_survives_a_later_declared_zero(self):
        self.assertVerdict(
            [review(HEAD, body=SUPPRESSED_UNDECLARED + "\n" + SUPPRESSED_EMPTY)],
            signals.TRIAGE_REQUIRED)

    def test_human_login_containing_copilot_is_not_a_verdict(self):
        """__typename excludes the human; the login match stays deliberately loose."""
        self.assertVerdict(
            [review(HEAD, login="copilotfan", typename="User")],
            signals.NOT_APPLICABLE)

    def test_historical_suppressed_block_does_not_keep_the_loop_dirty(self):
        """Head-scoping. Without it an already-fixed round never reaches clean."""
        self.assertVerdict(
            [review(OLD, body=SUPPRESSED_TWO), review(HEAD)], signals.CLEAN)

    def test_overview_known_clean_headline_is_clean(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_CLEAN)], signals.CLEAN)

    def test_overview_headline_concern_with_no_findings_requires_triage(self):
        """The headline is the only place the finding appears: no inline comment,
        `Findings: None`, no suppressed block. Read as clean, it ended the loop."""
        self.assertVerdict([review(HEAD, body=OVERVIEW_HEADLINE_CONCERN)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_clean_verdict_naming_a_remaining_nit_requires_triage(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_CLEAN_VERDICT_WITH_NIT)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_review_findings_list_requires_triage(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_REVIEW_FINDINGS_LIST)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_table_only_finding_requires_triage(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_TABLE_ONLY_FINDING)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_vote_tagged_finding_under_a_clean_headline_requires_triage(self):
        """Isolates the vote count from the headline: the verdict is the known-clean
        one and `Findings: None`, so only the per-file cell can trigger this."""
        self.assertVerdict([review(HEAD, body=OVERVIEW_CLEAN_VERDICT_TABLE_FINDING)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_unknown_headline_fails_closed(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_UNKNOWN_HEADLINE)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_without_a_parsable_headline_fails_closed(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_NO_HEADLINE)],
                           signals.TRIAGE_REQUIRED)

    def test_overview_resolved_since_last_review_votes_do_not_keep_the_loop_dirty(self):
        self.assertVerdict([review(HEAD, body=OVERVIEW_CLEAN_WITH_RESOLVED)],
                           signals.CLEAN)

    def test_overview_nested_resolved_findings_do_not_leak_into_body_only(self):
        """A resolved section with several nested findings is excluded as a whole;
        no child's vote tag leaks past a non-greedy details match."""
        self.assertVerdict([review(HEAD, body=OVERVIEW_CLEAN_NESTED_RESOLVED)],
                           signals.CLEAN)

    def test_overview_only_the_known_clean_sentence_is_clean(self):
        """The sentence is matched against an allow-list, not parsed. Case,
        surrounding whitespace, and trailing punctuation are normalised away."""
        for sentence in (
            "The changes are fully reviewed, tested, and have no unresolved blocking issues.",
            "the changes are fully reviewed, tested, and have no unresolved blocking issues",
            "  The changes are fully reviewed, tested, and have no unresolved blocking issues!  ",
        ):
            with self.subTest(sentence=sentence):
                body = OVERVIEW_CLEAN.replace(
                    "The changes are fully reviewed, tested, and have no unresolved "
                    "blocking issues.", sentence)
                self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_overview_clean_verdict_with_no_sentence_is_clean(self):
        """Verdict plus metadata, no prose paragraph: no claim to misread, and the
        structural counts still run."""
        body = (OVERVIEW_MARKER + "### 🟢 Approval recommended\n\n"
                "**Review effort:** Lite\n**Findings:** None\n")
        self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_overview_a_novel_sentence_fails_closed(self):
        """A sentence off the allow-list triages even when it reads clean to a
        human. That false-closed is the accepted cost: one human read, never a
        missed finding. These all read clean and all triage."""
        for sentence in ("No minor issues remain.",
                         "All three issues were resolved.",
                         "LGTM.",
                         "The changes look good and are well tested."):
            with self.subTest(sentence=sentence):
                body = OVERVIEW_CLEAN.replace(
                    "The changes are fully reviewed, tested, and have no unresolved "
                    "blocking issues.", sentence)
                self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_a_sentence_naming_a_leftover_requires_triage(self):
        """The load-bearing case: a green verdict with `Findings: None` whose only
        finding is in the sentence. Off the allow-list, so it triages."""
        for sentence in ("Only a minor naming nit remains.",
                         "No blocking issues, but a nit remains.",
                         "The minor nit was not fixed."):
            with self.subTest(sentence=sentence):
                body = OVERVIEW_CLEAN.replace(
                    "The changes are fully reviewed, tested, and have no unresolved "
                    "blocking issues.", sentence)
                self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_prose_appended_to_a_metadata_row_is_not_hidden(self):
        """A metadata row is the label plus its own short value. A concern appended
        to the row, with or without a trailing period, makes the line prose and must
        reach the allow-list, not be skipped by a prefix match."""
        for effort in ("Lite - a boundary case remains unhandled.",
                       "Lite and a boundary case remains unhandled",
                       "Lite. A boundary case remains unhandled."):
            with self.subTest(effort=effort):
                body = OVERVIEW_CLEAN.replace("**Review effort:** Lite",
                                              f"**Review effort:** {effort}")
                self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_prose_after_a_files_reviewed_ratio_is_not_hidden(self):
        """The Files reviewed value is the ratio and the literal "changed file(s)",
        not arbitrary trailing words that could carry a concern."""
        body = OVERVIEW_CLEAN.replace(
            "**Review effort:** Lite",
            "**Files reviewed:** 1/1 and a boundary case remains unhandled")
        self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_files_reviewed_row_is_still_metadata(self):
        body = (OVERVIEW_MARKER + "### 🟢 Approval recommended\n\n"
                "**Files reviewed:** 16/16 changed files\n**Findings:** None\n")
        self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_overview_emoji_prefixed_metadata_row_is_still_metadata(self):
        """The real layout prefixes the effort row with a badge emoji; it must still
        read as metadata so a verdict-plus-metadata body stays clean."""
        body = (OVERVIEW_MARKER + "### 🟢 Approval recommended\n\n"
                "🧠 **Review effort:** Balanced\n**Findings:** None\n")
        self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_overview_a_second_prose_paragraph_is_not_ignored(self):
        """Every non-metadata paragraph must be allow-listed. The known-clean
        sentence cannot carry a concern in a paragraph after it."""
        body = OVERVIEW_CLEAN.replace(
            "**Review effort:** Lite",
            "A boundary case remains unhandled.\n\n**Review effort:** Lite")
        self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_a_formatted_sentence_is_prose_not_skipped_metadata(self):
        """Only the known metadata labels are skipped. A bold- or markup-wrapped
        concern must read as a sentence and fail the allow-list, not vanish."""
        for sentence in ("**A boundary case remains.**",
                         "*A boundary case remains.*",
                         "<strong>A boundary case remains.</strong>"):
            with self.subTest(sentence=sentence):
                body = OVERVIEW_CLEAN.replace(
                    "The changes are fully reviewed, tested, and have no unresolved "
                    "blocking issues.", sentence)
                self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_unparsable_or_missing_findings_declaration_fails_closed(self):
        """An unreadable declaration is not "no findings". Read as absent it
        yields the same value as a clean review, which is the silent zero."""
        for replacement in ("**Findings:** Unknown", "**Findings:**", "Findings: None", "",
                            "**Findings:** NoneAvailable", "**Findings:** 0unknown",
                            "**Findings:** None2", "**Findings:** 0.5", "**Findings:** 1.0",
                            "**Findings:** None A boundary case remains unhandled.",
                            "**Findings:** 0 a boundary case remains unhandled"):
            with self.subTest(replacement=replacement):
                body = OVERVIEW_CLEAN.replace("**Findings:** None", replacement)
                self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_labelled_block_with_an_unreadable_count_fails_closed(self):
        """"Previously missed" and "Open" carry findings. A label with no readable
        number is not zero."""
        for label in ("Previously missed", "Previously missed (several)",
                      "Open", "Open (many)"):
            with self.subTest(label=label):
                body = OVERVIEW_CLEAN + (
                    f"\n<details>\n<summary><strong>{label}</strong></summary>\n\n"
                    "Something.\n</details>\n")
                self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_declared_counts_with_a_severity_suffix_still_parse(self):
        body = OVERVIEW_CLEAN.replace("**Findings:** None", "**Findings:** 0 low")
        self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_overview_previously_missed_block_requires_triage(self):
        """Under a clean headline: the block is the only place the finding appears."""
        body = OVERVIEW_CLEAN + PREVIOUSLY_MISSED_BLOCK.format(count=1)
        self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_previously_missed_zero_and_genuinely_empty_is_clean(self):
        body = OVERVIEW_CLEAN + (
            "\n<details>\n<summary><strong>Previously missed (0)</strong></summary>\n\n"
            "In code that hasn't changed since last review\n</details>\n")
        self.assertVerdict([review(HEAD, body=body)], signals.CLEAN)

    def test_overview_previously_missed_zero_with_nested_entries_requires_triage(self):
        """A (0) label over a block that still lists findings is a silent zero: the
        declared count is not trusted against the block's actual entries."""
        body = OVERVIEW_CLEAN + PREVIOUSLY_MISSED_BLOCK.format(count=0)
        self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_details_block_without_a_summary_fails_closed(self):
        """A top-level block whose summary cannot be read is a parse failure, not a
        benign block; its content is dropped from the sentence, so it must triage."""
        body = OVERVIEW_CLEAN + (
            "\n<details>\n\nA boundary case remains unhandled.\n</details>\n")
        self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_nested_summary_is_not_read_as_the_outer_blocks_own(self):
        """An outer block with no summary must not borrow a nested child's. A nested
        "Resolved" summary could otherwise exclude the whole outer block and drop an
        unresolved concern in it."""
        body = OVERVIEW_CLEAN + (
            "\n<details>\n"
            "<details><summary><strong>1 resolved since last review</strong></summary>\n"
            "- an old finding\n</details>\n"
            "A boundary case remains unhandled.\n</details>\n")
        self.assertVerdict([review(HEAD, body=body)], signals.TRIAGE_REQUIRED)

    def test_overview_marker_is_scoped_to_the_review_at_head(self):
        self.assertVerdict(
            [review(OLD, body=OVERVIEW_HEADLINE_CONCERN), review(HEAD, body=OVERVIEW_CLEAN)],
            signals.CLEAN)


class ReportTests(unittest.TestCase):
    """The printed report is the other half of the interface.

    The exit status cannot express `pending`, and the loop's re-request gate
    reads it, so both branches need cover. Left untested it is the signal whose
    failure mode is a watcher that waits through a landed review.
    """

    def report(self, reviews, head=HEAD, pending=()):
        return ClassificationTests.verdict(self, reviews, head, pending)[1]

    _run = ClassificationTests._run

    def test_reports_no_pending_request(self):
        self.assertIn("pending none", self.report([review(HEAD)]))

    def test_reports_a_pending_request(self):
        out = self.report([review(HEAD)], pending=["copilot-pull-request-reviewer"])
        self.assertIn("copilot-pull-request-reviewer", out.splitlines()[1])

    def test_non_copilot_requested_reviewer_is_not_reported_as_pending(self):
        self.assertIn("pending none",
                      self.report([review(HEAD)], pending=["some-human"]))

    def test_human_reviewer_named_like_the_bot_is_not_reported_as_pending(self):
        """Login alone is not enough; a User reading as pending parks the loop.

        Requesting a human whose login contains "copilot" would otherwise send
        step 2 into wait instead of re-requesting, with nothing ever landing.
        """
        self.assertIn("pending none",
                      self.report([review(HEAD)], pending=[("copilotfan", "User")]))

    def test_bot_request_is_still_reported_when_a_human_lookalike_coexists(self):
        out = self.report([review(HEAD)], pending=[
            ("copilotfan", "User"), ("copilot-pull-request-reviewer", "Bot")])
        self.assertIn("copilot-pull-request-reviewer", out)
        self.assertNotIn("copilotfan", out)

    def test_reports_head_and_each_review(self):
        out = self.report([review(OLD), review(HEAD, inline=2)])
        self.assertIn(f"head {HEAD}", out)
        self.assertIn("AT HEAD", out)
        self.assertEqual(out.count("=== review"), 2)

    def test_warns_when_declared_and_parsed_counts_disagree(self):
        self.assertIn("WARNING", self.report(
            [review(HEAD, body=SUPPRESSED_ZERO_WITH_FINDINGS)]))

    def test_no_spurious_warning_when_a_block_is_undeclared(self):
        """count sums declared blocks while findings span all of them."""
        self.assertNotIn("WARNING", self.report(
            [review(HEAD, body=SUPPRESSED_UNDECLARED + "\n" + SUPPRESSED_EMPTY)]))

    def test_prints_the_headline_so_a_headline_only_triage_is_readable(self):
        out = self.report([review(HEAD, body=OVERVIEW_HEADLINE_CONCERN)])
        self.assertIn('headline="Needs a closer look: '
                      'The boundary case in the changed component is not handled."', out)

    def test_reports_an_unparsable_headline_instead_of_crashing(self):
        out = self.report([review(HEAD, body=OVERVIEW_NO_HEADLINE)])
        self.assertIn("headline=UNPARSABLE", out)

    def test_prints_body_only_count_as_its_own_field(self):
        out = self.report([review(HEAD, body=OVERVIEW_TABLE_ONLY_FINDING)])
        self.assertIn("inline=0 suppressed=none body_only=1", out)

    def test_body_only_is_not_applicable_without_the_overview_layout(self):
        self.assertIn("body_only=n/a", self.report([review(HEAD, body=BENIGN)]))

    def test_names_the_reasons_in_the_triage_line(self):
        out = self.report([review(HEAD, body=OVERVIEW_HEADLINE_CONCERN)])
        self.assertIn("TRIAGE REQUIRED", out)
        self.assertIn("Needs a closer look", out.splitlines()[-1])


class ErrorPathTests(unittest.TestCase):
    """Every failure must land on ERROR rather than on a verdict.

    These run the script as a subprocess with a stubbed `gh` so they stay
    offline, which is what lets CI cover the top-level handler.
    """

    def run_with_gh(self, stdout="", returncode=0, stderr=""):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "gh"
            stub.write_text(textwrap.dedent(f"""\
                #!/bin/sh
                cat <<'STUB_EOF'
                {stdout}
                STUB_EOF
                printf '%s' {json.dumps(stderr)} >&2
                exit {returncode}
                """))
            stub.chmod(0o755)
            env = dict(os.environ)
            # Prepend. Replacing PATH would break the stub's own `cat`, and every
            # case would still exit 3 while asserting nothing.
            env["PATH"] = tmp + os.pathsep + env["PATH"]
            return subprocess.run(
                [sys.executable, str(SCRIPT), "owner", "repo", "1"],
                capture_output=True, text=True, env=env)

    def assertNoVerdict(self, result):
        self.assertEqual(result.returncode, signals.ERROR)
        self.assertIn("ERROR", result.stderr)

    def test_gh_failure_is_error(self):
        self.assertNoVerdict(self.run_with_gh(returncode=1, stderr="gh: auth required"))

    def test_graphql_errors_payload_is_error(self):
        self.assertNoVerdict(self.run_with_gh(stdout=json.dumps(
            {"data": None, "errors": [{"message": "Could not resolve to a Repository"}]})))

    def test_malformed_json_is_error(self):
        self.assertNoVerdict(self.run_with_gh(stdout="not json at all"))

    def test_null_repository_is_error(self):
        result = self.run_with_gh(stdout=json.dumps({"data": {"repository": None}}))
        self.assertNoVerdict(result)
        # The exit status was always right; the message was "'NoneType' object is
        # not subscriptable", which tells the reader nothing about what to fix.
        self.assertIn("no such repository, or no access", result.stderr)

    def test_null_pull_request_is_error(self):
        result = self.run_with_gh(stdout=json.dumps(
            {"data": {"repository": {"pullRequest": None}}}))
        self.assertNoVerdict(result)
        self.assertIn("no pull request 1", result.stderr)

    def test_stub_reaches_a_real_verdict_on_a_well_formed_payload(self):
        """Guards the stub itself: without this the cases above could pass vacuously."""
        result = self.run_with_gh(stdout=json.dumps(
            {"data": {"repository": {"pullRequest": payload([review(HEAD)])}}}))
        self.assertEqual(result.returncode, signals.CLEAN)
        self.assertIn("CLEAN", result.stdout)


class ParserTests(unittest.TestCase):
    def test_matches_both_observed_labels(self):
        for body, expected in ((SUPPRESSED_TWO, 2), (OLD_LABEL, 3)):
            with self.subTest(body=body[:40]):
                count, _, labels, _ = signals.parse_suppressed(body)
                self.assertEqual(count, expected)
                self.assertTrue(labels)

    def test_ignores_benign_details_block(self):
        count, findings, labels, _ = signals.parse_suppressed(BENIGN)
        self.assertIsNone(count)
        self.assertEqual(findings, [])
        self.assertEqual(labels, [])

    def test_unparsable_count_is_none_not_zero(self):
        count, findings, labels, _ = signals.parse_suppressed(SUPPRESSED_UNDECLARED)
        self.assertIsNone(count)
        self.assertTrue(labels)
        self.assertEqual(len(findings), 1)

    def test_extracts_file_and_text_per_finding(self):
        _, findings, _, _ = signals.parse_suppressed(SUPPRESSED_TWO)
        self.assertEqual([path for path, _ in findings], ["src/a.py", "src/b.py"])

    def test_suppressed_and_benign_blocks_coexist(self):
        count, findings, _, _ = signals.parse_suppressed(BENIGN + "\n" + SUPPRESSED_TWO)
        self.assertEqual(count, 2)
        self.assertEqual(len(findings), 2)

    def test_parses_label_inside_review_details_body(self):
        """The label is a heading in the block body, not the <summary>."""
        count, findings, labels, undeclared = signals.parse_suppressed(REVIEW_DETAILS_SUPPRESSED)
        self.assertEqual(count, 1)
        self.assertFalse(undeclared)
        self.assertTrue(labels)
        self.assertEqual([path for path, _ in findings],
                         ["src/components/FeatureCard/index.tsx:35"])

    def test_bold_metadata_rows_are_not_findings(self):
        """**Files reviewed:** and **Previously missed (N)** share the bold markup
        with the file paths but are not paths, so they must not be counted."""
        _, findings, _, _ = signals.parse_suppressed(REVIEW_DETAILS_SUPPRESSED)
        self.assertEqual(len(findings), 1)

    def test_review_details_mentioning_suppress_is_not_suppressed(self):
        count, findings, labels, _ = signals.parse_suppressed(
            REVIEW_DETAILS_CLEAN_MENTIONS_SUPPRESS)
        self.assertIsNone(count)
        self.assertEqual(findings, [])
        self.assertEqual(labels, [])


class OverviewParserTests(unittest.TestCase):
    def test_body_without_the_marker_is_not_an_overview(self):
        self.assertIsNone(signals.parse_overview(REVIEW_DETAILS_SUPPRESSED, inline=0))

    def test_extracts_verdict_and_sentence_without_the_emoji(self):
        overview = signals.parse_overview(OVERVIEW_HEADLINE_CONCERN, inline=0)
        self.assertEqual(overview.verdict, "Needs a closer look")
        self.assertEqual(overview.sentence,
                         "The boundary case in the changed component is not handled.")

    def test_known_clean_sample_has_no_reasons(self):
        overview = signals.parse_overview(OVERVIEW_CLEAN, inline=0)
        self.assertEqual(overview.reasons, [])
        self.assertEqual(overview.body_only, 0)

    def test_counts_review_findings_list_items(self):
        overview = signals.parse_overview(OVERVIEW_REVIEW_FINDINGS_LIST, inline=0)
        self.assertEqual(overview.body_only, 2)

    def test_table_only_finding_is_the_surplus_over_open(self):
        overview = signals.parse_overview(OVERVIEW_TABLE_ONLY_FINDING, inline=0)
        self.assertEqual((overview.declared, overview.open_count, overview.body_only),
                         (2, 2, 1))

    def test_previously_missed_findings_count_as_body_only(self):
        body = OVERVIEW_CLEAN + PREVIOUSLY_MISSED_BLOCK.format(count=2)
        self.assertEqual(signals.parse_overview(body, inline=0).body_only, 2)

    def test_one_finding_in_both_list_and_table_counts_once(self):
        overview = signals.parse_overview(OVERVIEW_FINDING_IN_LIST_AND_TABLE, inline=0)
        self.assertEqual(overview.body_only, 1)

    def test_table_findings_beyond_the_list_still_count(self):
        """The list is not assumed to be complete: the larger section wins."""
        body = OVERVIEW_FINDING_IN_LIST_AND_TABLE.replace(
            "(2 votes). |\n", "(2 votes). |\n| `src/b.ts` | Change. Issue: a retry has no cap (1 vote). |\n")
        self.assertEqual(signals.parse_overview(body, inline=0).body_only, 2)

    def test_inline_threads_account_for_body_findings(self):
        """Inline comments are already triage-required; they also stop the same
        finding from being counted twice as body-only."""
        overview = signals.parse_overview(OVERVIEW_REVIEW_FINDINGS_LIST, inline=3)
        self.assertEqual(overview.body_only, 0)

    def test_a_sentence_off_the_allow_list_is_a_reason(self):
        """Clean verdict, so the sentence check (an elif under it) actually runs."""
        overview = signals.parse_overview(OVERVIEW_CLEAN_VERDICT_WITH_NIT, inline=0)
        self.assertTrue(any("known-clean sentence" in reason for reason in overview.reasons))

    def test_nested_resolved_section_contributes_no_body_only(self):
        overview = signals.parse_overview(OVERVIEW_CLEAN_NESTED_RESOLVED, inline=0)
        self.assertEqual(overview.body_only, 0)

    def test_a_non_resolved_nested_section_still_counts_its_findings(self):
        """The whole-range exclusion applies only to resolved sections: a kept
        section's nested vote tags are still counted."""
        body = OVERVIEW_CLEAN_NESTED_RESOLVED.replace(
            "2 resolved since last review", "2 open findings")
        self.assertEqual(signals.parse_overview(body, inline=0).body_only, 2)

    def test_a_future_marker_version_is_parsed_but_never_clean(self):
        """The layout is verified for v2 only. A later version can move findings
        somewhere this parser does not read, so a clean-looking v3 body is not
        evidence of anything."""
        body = OVERVIEW_CLEAN.replace("ccr-overview-v2", "ccr-overview-v3")
        overview = signals.parse_overview(body, inline=0)
        self.assertIsNotNone(overview)
        self.assertTrue(any("v3" in reason for reason in overview.reasons))

    def test_the_verified_marker_version_adds_no_reason(self):
        self.assertEqual(signals.parse_overview(OVERVIEW_CLEAN, inline=0).reasons, [])


class ArgumentTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(["python3", str(SCRIPT), *args],
                              capture_output=True, text=True).returncode

    def test_no_arguments_is_error(self):
        self.assertEqual(self.run_script(), signals.ERROR)

    def test_non_integer_pr_number_is_error(self):
        """Never let a bad argument land on a verdict exit code."""
        self.assertEqual(self.run_script("owner", "repo", "abc"), signals.ERROR)


@unittest.skipUnless(os.environ.get("SIGNALS_LIVE"), "needs network and gh auth")
class LiveTests(unittest.TestCase):
    """Known-answer cases against merged PRs, whose state cannot drift."""

    def run_script(self, number):
        return subprocess.run(
            ["python3", str(SCRIPT), "dgowrie", "claude-workflows", str(number)],
            capture_output=True, text=True)

    def test_pr_72_has_no_review_at_head(self):
        """Merged with its last review two commits back."""
        self.assertEqual(self.run_script(72).returncode, signals.NOT_APPLICABLE)

    def test_pr_72_reproduces_both_label_variants(self):
        out = self.run_script(72).stdout
        self.assertIn("Comments suppressed due to low confidence (1)", out)
        self.assertIn("Suppressed comments (4)", out)

    def test_pr_81_is_clean_at_head(self):
        self.assertEqual(self.run_script(81).returncode, signals.CLEAN)

    def test_unknown_repo_is_error(self):
        result = subprocess.run(
            ["python3", str(SCRIPT), "dgowrie", "no-such-repo-xyz", "1"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, signals.ERROR)


if __name__ == "__main__":
    unittest.main()
