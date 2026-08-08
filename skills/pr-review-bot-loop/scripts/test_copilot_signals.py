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
import os
import subprocess
import sys
import unittest
from pathlib import Path

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


def review(oid, inline=0, body="", when="2026-01-01T00:00:00Z",
           login="copilot-pull-request-reviewer"):
    return {"author": {"login": login}, "submittedAt": when,
            "commit": {"oid": oid}, "comments": {"totalCount": inline},
            "body": body}


class ClassificationTests(unittest.TestCase):
    """Every path that decides whether the loop terminates."""

    def _run(self):
        argv = sys.argv
        sys.argv = ["copilot-signals.py", "owner", "repo", "1"]
        try:
            return signals.main()
        finally:
            sys.argv = argv

    def assertVerdict(self, reviews, expected, head=HEAD):
        signals.fetch = lambda owner, repo, number: {
            "headRefOid": head,
            "reviewRequests": {"nodes": []},
            "reviews": {"nodes": reviews},
        }
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self._run(), expected)

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

    def test_historical_suppressed_block_does_not_keep_the_loop_dirty(self):
        """Head-scoping. Without it an already-fixed round never reaches clean."""
        self.assertVerdict(
            [review(OLD, body=SUPPRESSED_TWO), review(HEAD)], signals.CLEAN)


class ParserTests(unittest.TestCase):
    def test_matches_both_observed_labels(self):
        for body, expected in ((SUPPRESSED_TWO, 2), (OLD_LABEL, 3)):
            with self.subTest(body=body[:40]):
                count, _, labels = signals.parse_suppressed(body)
                self.assertEqual(count, expected)
                self.assertTrue(labels)

    def test_ignores_benign_details_block(self):
        count, findings, labels = signals.parse_suppressed(BENIGN)
        self.assertIsNone(count)
        self.assertEqual(findings, [])
        self.assertEqual(labels, [])

    def test_unparsable_count_is_none_not_zero(self):
        count, findings, labels = signals.parse_suppressed(SUPPRESSED_UNDECLARED)
        self.assertIsNone(count)
        self.assertTrue(labels)
        self.assertEqual(len(findings), 1)

    def test_extracts_file_and_text_per_finding(self):
        _, findings, _ = signals.parse_suppressed(SUPPRESSED_TWO)
        self.assertEqual([path for path, _ in findings], ["src/a.py", "src/b.py"])

    def test_suppressed_and_benign_blocks_coexist(self):
        count, findings, _ = signals.parse_suppressed(BENIGN + "\n" + SUPPRESSED_TWO)
        self.assertEqual(count, 2)
        self.assertEqual(len(findings), 2)


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
