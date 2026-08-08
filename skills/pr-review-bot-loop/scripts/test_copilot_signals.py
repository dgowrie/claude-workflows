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
        self.assertNoVerdict(self.run_with_gh(stdout=json.dumps(
            {"data": {"repository": None}})))

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
