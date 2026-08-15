#!/usr/bin/env python3
"""Tests for preflight.py.

    python3 -m unittest discover -s skills/pickup/scripts -v

Fully offline. Git facts run against real temporary repositories rather than
stubs, because the questions preflight asks git ("is this tree dirty", "am I on
the default branch") are exactly the ones a stub would answer by restating the
test's own assumption. The `gh` half is patched instead: it needs network and an
authenticated CLI, and CI has neither.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("preflight.py")


def load():
    spec = importlib.util.spec_from_file_location("preflight", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = load()

GIT_IDENTITY = [
    "-c", "user.name=Test",
    "-c", "user.email=test@example.com",
    "-c", "commit.gpgsign=false",
]


def git(repo, *args):
    subprocess.run(
        ["git", *GIT_IDENTITY, *args],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_repo(default_branch="main"):
    """A committed repo on `default_branch`, with no remote.

    `git init -b` would be shorter but only exists from git 2.28; setting HEAD
    directly keeps the fixture working on whatever git the runner ships.
    """
    path = Path(tempfile.mkdtemp())
    git(path, "init", "-q")
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/" + default_branch],
        cwd=path,
        check=True,
    )
    (path / "README.md").write_text("seed\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "seed")
    return path


def make_handoff_doc(name="handoff-thing.md"):
    """A handoff document outside any repository.

    `/handoff` writes to the OS temp directory, not the workspace, and the
    fixture has to match: dropping the document inside the repo under test would
    make the tree dirty and trip the very blocker these tests exercise.
    """
    doc = Path(tempfile.mkdtemp()) / name
    doc.write_text("# Handoff\n")
    return str(doc)


class GitFacts(unittest.TestCase):
    def test_clean_repo_on_default_branch(self):
        repo = make_repo()
        facts = preflight.git_facts(repo)
        self.assertEqual(Path(facts["repo_root"]).resolve(), repo.resolve())
        self.assertEqual(facts["current_branch"], "main")
        self.assertTrue(facts["tree_clean"])
        self.assertEqual(facts["dirty_paths"], [])
        self.assertTrue(facts["on_default_branch"])

    def test_feature_branch_is_not_default(self):
        repo = make_repo()
        git(repo, "checkout", "-q", "-b", "feat/thing")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["current_branch"], "feat/thing")
        self.assertFalse(facts["on_default_branch"])

    def test_master_repo_detected_as_default(self):
        repo = make_repo(default_branch="master")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["default_branch"], "master")
        self.assertTrue(facts["on_default_branch"])

    def test_modified_file_is_dirty(self):
        repo = make_repo()
        (repo / "README.md").write_text("changed\n")
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["tree_clean"])
        self.assertIn("README.md", facts["dirty_paths"])

    def test_untracked_file_is_dirty(self):
        """Untracked counts. An unattended run must not bulldoze work whose
        origin it cannot establish, and untracked files are the case where it
        has the least idea what it would be destroying."""
        repo = make_repo()
        (repo / "stray.txt").write_text("who put this here\n")
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["tree_clean"])
        self.assertIn("stray.txt", facts["dirty_paths"])

    def test_staged_file_is_dirty(self):
        repo = make_repo()
        (repo / "new.txt").write_text("staged\n")
        git(repo, "add", "new.txt")
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["tree_clean"])
        self.assertIn("new.txt", facts["dirty_paths"])

    def test_failed_status_reports_unknown_rather_than_clean(self):
        """A gate that fails open is worse than no gate. When `git status`
        fails its output is empty, which looks exactly like a clean tree; the
        run must refuse rather than proceed on an unknown tree state."""
        repo = make_repo()
        real_run = preflight.run

        def fake_run(args, cwd):
            if "status" in args:
                return 1, ""
            return real_run(args, cwd)

        with mock.patch.object(preflight, "run", side_effect=fake_run):
            facts = preflight.git_facts(repo)
        self.assertFalse(facts["status_ok"])
        self.assertFalse(facts["tree_clean"])

    def test_successful_status_is_marked_ok(self):
        repo = make_repo()
        facts = preflight.git_facts(repo)
        self.assertTrue(facts["status_ok"])

    def test_non_repo_reports_no_root(self):
        outside = Path(tempfile.mkdtemp())
        facts = preflight.git_facts(outside)
        self.assertIsNone(facts["repo_root"])


class Codeowners(unittest.TestCase):
    def test_absent_file_yields_no_owners(self):
        repo = make_repo()
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertIsNone(result["file"])
        self.assertEqual(result["owners"], [])

    def test_glob_rule_matches(self):
        repo = make_repo()
        (repo / ".github").mkdir()
        (repo / ".github" / "CODEOWNERS").write_text("* @default-owner\n")
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertEqual(result["owners"], ["@default-owner"])
        self.assertTrue(result["file"].endswith(".github/CODEOWNERS"))

    def test_last_matching_rule_wins(self):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text(
            "* @default-owner\n"
            "skills/ @skills-team\n"
        )
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertEqual(result["owners"], ["@skills-team"])

    def test_comments_and_blank_lines_ignored(self):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text(
            "# ownership\n"
            "\n"
            "*.md @docs-team\n"
        )
        result = preflight.codeowners_for(repo, ["README.md"])
        self.assertEqual(result["owners"], ["@docs-team"])

    def test_owners_from_several_paths_are_unioned(self):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text(
            "skills/ @skills-team\n"
            "*.yml @ci-team\n"
        )
        result = preflight.codeowners_for(
            repo, ["skills/pickup/SKILL.md", ".github/workflows/tests.yml"]
        )
        self.assertEqual(sorted(result["owners"]), ["@ci-team", "@skills-team"])

    def test_unmatched_path_contributes_nothing(self):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text("docs/ @docs-team\n")
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertEqual(result["owners"], [])
        self.assertTrue(result["readable"])

    def test_star_does_not_cross_a_path_separator(self):
        """Python's fnmatch lets `*` match `/`, so `docs/*.md` would otherwise
        claim ownership of `docs/sub/file.md` and name the wrong reviewer."""
        repo = make_repo()
        (repo / "CODEOWNERS").write_text("docs/*.md @docs-team\n")
        nested = preflight.codeowners_for(repo, ["docs/sub/file.md"])
        self.assertEqual(nested["owners"], [])
        direct = preflight.codeowners_for(repo, ["docs/file.md"])
        self.assertEqual(direct["owners"], ["@docs-team"])

    def test_directory_prefix_still_matches_at_any_depth(self):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text("skills/ @skills-team\n")
        result = preflight.codeowners_for(repo, ["skills/pickup/scripts/preflight.py"])
        self.assertEqual(result["owners"], ["@skills-team"])

    def test_undecodable_file_reports_unreadable_rather_than_no_owners(self):
        """An empty owner list must mean "no rule matched", never "the file
        could not be read". Collapsing the two is a silent zero: the run would
        report nobody owns the code when it simply failed to look."""
        repo = make_repo()
        (repo / "CODEOWNERS").write_bytes(b"\xff\xfe* @default-owner\n")
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertFalse(result["readable"])
        self.assertEqual(result["owners"], [])

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root reads regardless of mode bits",
    )
    def test_unreadable_file_does_not_raise(self):
        repo = make_repo()
        owners_file = repo / "CODEOWNERS"
        owners_file.write_text("* @default-owner\n")
        owners_file.chmod(0o000)
        try:
            result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        finally:
            owners_file.chmod(0o644)
        self.assertFalse(result["readable"])
        self.assertEqual(result["owners"], [])

    def test_absent_file_counts_as_readable(self):
        """No CODEOWNERS is a known state, not a failure to read one."""
        repo = make_repo()
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertTrue(result["readable"])


class GhOpenPrs(unittest.TestCase):
    """`None` means the lookup failed; `[]` means the repo genuinely has no open
    PRs. Collapsing them is a silent zero with an outward-facing consequence: a
    resume that cannot see its own PR opens a duplicate one."""

    def test_valid_empty_list_is_empty(self):
        with mock.patch.object(preflight, "run", return_value=(0, "[]\n")):
            self.assertEqual(preflight.gh_open_prs("."), [])

    def test_populated_list_is_parsed(self):
        payload = '[{"number": 3, "body": "x"}]'
        with mock.patch.object(preflight, "run", return_value=(0, payload)):
            self.assertEqual(preflight.gh_open_prs(".")[0]["number"], 3)

    def test_command_failure_is_none(self):
        with mock.patch.object(preflight, "run", return_value=(1, "")):
            self.assertIsNone(preflight.gh_open_prs("."))

    def test_unparsable_output_is_none(self):
        with mock.patch.object(preflight, "run", return_value=(0, "not json")):
            self.assertIsNone(preflight.gh_open_prs("."))

    def test_empty_output_is_none(self):
        """`gh pr list --json` prints `[]` when there is nothing. Silence means
        something went wrong, so it is a failure rather than an empty result."""
        with mock.patch.object(preflight, "run", return_value=(0, "")):
            self.assertIsNone(preflight.gh_open_prs("."))


class FindRunPr(unittest.TestCase):
    """Resume detection. Keyed on the handoff document a PR body cites, not on
    the branch name, so a run resumes even from a differently named branch."""

    HANDOFF = "/tmp/scratch/handoff-featurecard-layout.md"

    def test_no_open_prs(self):
        self.assertIsNone(preflight.find_run_pr([], self.HANDOFF))

    def test_body_citing_the_handoff_matches(self):
        prs = [{"number": 7, "body": "Picked up from handoff-featurecard-layout.md"}]
        self.assertEqual(preflight.find_run_pr(prs, self.HANDOFF)["number"], 7)

    def test_unrelated_prs_do_not_match(self):
        prs = [
            {"number": 4, "body": "unrelated work"},
            {"number": 5, "body": "handoff-other-thing.md"},
        ]
        self.assertIsNone(preflight.find_run_pr(prs, self.HANDOFF))

    def test_lowest_number_wins_when_several_match(self):
        """Two PRs citing one handoff means an earlier run was abandoned rather
        than resumed. The older one is the run to rejoin."""
        prs = [
            {"number": 9, "body": "handoff-featurecard-layout.md"},
            {"number": 3, "body": "handoff-featurecard-layout.md"},
        ]
        self.assertEqual(preflight.find_run_pr(prs, self.HANDOFF)["number"], 3)

    def test_missing_body_is_tolerated(self):
        prs = [{"number": 2}, {"number": 3, "body": None}]
        self.assertIsNone(preflight.find_run_pr(prs, self.HANDOFF))


class Blockers(unittest.TestCase):
    """Only mechanically determinable blockers belong here. Semantic ones (a doc
    contradicting its issue, an irreversible change) stay model judgment in
    TRIAGE.md; this script must never appear to have ruled on them."""

    def collect(self, repo, handoff, prs=None, authed=True):
        with mock.patch.object(preflight, "gh_open_prs", return_value=prs or []), \
             mock.patch.object(preflight, "gh_authenticated", return_value=authed):
            return preflight.collect(repo, handoff)

    def test_clean_run_has_no_blockers(self):
        repo = make_repo()
        git(repo, "checkout", "-q", "-b", "feat/thing")
        result = self.collect(repo, make_handoff_doc())
        self.assertEqual(result["blockers"], [])

    def test_dirty_tree_blocks(self):
        repo = make_repo()
        (repo / "stray.txt").write_text("x\n")
        result = self.collect(repo, make_handoff_doc())
        self.assertIn("dirty-tree", [b["code"] for b in result["blockers"]])

    def test_missing_handoff_doc_blocks(self):
        repo = make_repo()
        result = self.collect(repo, str(repo / "nope.md"))
        self.assertIn(
            "handoff-doc-unreadable", [b["code"] for b in result["blockers"]]
        )

    def test_non_repo_blocks(self):
        outside = Path(tempfile.mkdtemp())
        result = self.collect(outside, make_handoff_doc())
        self.assertIn("not-a-git-repo", [b["code"] for b in result["blockers"]])

    def test_unauthenticated_gh_blocks(self):
        repo = make_repo()
        result = self.collect(repo, make_handoff_doc(), authed=False)
        self.assertIn("gh-unauthenticated", [b["code"] for b in result["blockers"]])

    def test_default_branch_is_not_a_blocker(self):
        """Sitting on main is the expected starting state; the skill branches
        from it. Blocking here would reject the common case."""
        repo = make_repo()
        result = self.collect(repo, make_handoff_doc())
        self.assertNotIn("on-default-branch", [b["code"] for b in result["blockers"]])
        self.assertTrue(result["on_default_branch"])

    def test_every_blocker_carries_a_detail(self):
        repo = make_repo()
        (repo / "stray.txt").write_text("x\n")
        result = self.collect(repo, str(repo / "nope.md"), authed=False)
        self.assertTrue(result["blockers"])
        for blocker in result["blockers"]:
            self.assertTrue(blocker.get("detail"), blocker)


class Resume(unittest.TestCase):
    def test_existing_pr_is_surfaced(self):
        repo = make_repo()
        doc = make_handoff_doc()
        prs = [{"number": 11, "body": "handoff-thing.md", "url": "u", "headRefName": "feat/thing"}]
        with mock.patch.object(preflight, "gh_open_prs", return_value=prs), \
             mock.patch.object(preflight, "gh_authenticated", return_value=True):
            result = preflight.collect(repo, doc)
        self.assertEqual(result["existing_pr"]["number"], 11)

    def test_absent_pr_is_null(self):
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=[]), \
             mock.patch.object(preflight, "gh_authenticated", return_value=True):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIsNone(result["existing_pr"])

    def test_failed_git_status_blocks(self):
        repo = make_repo()
        real_run = preflight.run

        def fake_run(args, cwd):
            if "status" in args:
                return 1, ""
            return real_run(args, cwd)

        with mock.patch.object(preflight, "run", side_effect=fake_run), \
             mock.patch.object(preflight, "gh_open_prs", return_value=[]), \
             mock.patch.object(preflight, "gh_authenticated", return_value=True):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIn("git-status-failed", [b["code"] for b in result["blockers"]])

    def test_failed_lookup_blocks_rather_than_reporting_no_pr(self):
        """Proceeding on a failed lookup would open a second PR for a run that
        already has one, unattended and outward-facing."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=None), \
             mock.patch.object(preflight, "gh_authenticated", return_value=True):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIn("pr-lookup-failed", [b["code"] for b in result["blockers"]])
        self.assertIsNone(result["existing_pr"])

    def test_genuinely_empty_lookup_does_not_block(self):
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=[]), \
             mock.patch.object(preflight, "gh_authenticated", return_value=True):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertNotIn("pr-lookup-failed", [b["code"] for b in result["blockers"]])

    def test_unauthenticated_gh_does_not_also_report_lookup_failure(self):
        """One root cause, one blocker. The gh-unauthenticated blocker already
        explains why no lookup happened."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_authenticated", return_value=False):
            result = preflight.collect(repo, make_handoff_doc())
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("gh-unauthenticated", codes)
        self.assertNotIn("pr-lookup-failed", codes)

    def test_pr_lookup_skipped_when_gh_unauthenticated(self):
        """No auth means no reliable answer about existing PRs. Reporting null
        as though the lookup succeeded would let a resume silently restart."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs") as lookup, \
             mock.patch.object(preflight, "gh_authenticated", return_value=False):
            result = preflight.collect(repo, make_handoff_doc())
        lookup.assert_not_called()
        self.assertIsNone(result["existing_pr"])


class Cli(unittest.TestCase):
    def run_main(self, argv, prs=None, authed=True):
        out = []
        with mock.patch.object(preflight, "gh_open_prs", return_value=prs or []), \
             mock.patch.object(preflight, "gh_authenticated", return_value=authed), \
             mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(a[0] if a else "")):
            code = preflight.main(argv)
        return code, "\n".join(str(line) for line in out)

    def test_clean_run_exits_zero_with_json(self):
        repo = make_repo()
        git(repo, "checkout", "-q", "-b", "feat/thing")
        code, output = self.run_main(
            ["--handoff-doc", make_handoff_doc(), "--cwd", str(repo)]
        )
        self.assertEqual(code, preflight.CLEAR)
        parsed = json.loads(output)
        self.assertEqual(parsed["current_branch"], "feat/thing")

    def test_blocked_run_exits_one_and_still_emits_json(self):
        """The blocked exit still prints the full fact set. A gate that reports
        only its verdict forces the caller to re-derive why."""
        repo = make_repo()
        (repo / "stray.txt").write_text("x\n")
        code, output = self.run_main(
            ["--handoff-doc", make_handoff_doc(), "--cwd", str(repo)]
        )
        self.assertEqual(code, preflight.BLOCKED)
        parsed = json.loads(output)
        self.assertTrue(parsed["blockers"])

    def test_missing_required_argument_is_a_usage_error(self):
        code, _ = self.run_main(["--cwd", "/tmp"])
        self.assertEqual(code, preflight.USAGE_ERROR)

    def test_help_exits_zero(self):
        """`--help` is a successful request for help, not a usage error.
        argparse already encodes that distinction in the code it raises with;
        flattening every SystemExit discards it."""
        with contextlib.redirect_stdout(io.StringIO()):
            code = preflight.main(["--help"])
        self.assertEqual(code, preflight.CLEAR)


if __name__ == "__main__":
    unittest.main()
