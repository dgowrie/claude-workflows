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
import re
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
REAL_RUN = preflight.run

_isolated_environment = None


def setUpModule():
    """Hide the developer's git configuration from every git call, including
    the ones preflight itself makes.

    Patching only the fixture helper would leave `git_facts` reading the host's
    config, so a local `status.showUntrackedFiles=no` or `core.hooksPath` would
    change results on one machine and not another. `GIT_CONFIG_GLOBAL` needs git
    2.32; pointing `HOME` and `XDG_CONFIG_HOME` at an empty directory covers
    older git too.
    """
    global _isolated_environment
    empty_home = tempfile.mkdtemp()
    _isolated_environment = mock.patch.dict(os.environ, {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": empty_home,
        "XDG_CONFIG_HOME": empty_home,
    })
    _isolated_environment.start()
    # `patch.dict` cannot delete keys; `stop` restores it. Left set, it
    # overrides the remote-derived host every GhAuthState test asserts.
    os.environ.pop("GH_HOST", None)


def tearDownModule():
    _isolated_environment.stop()


VIEWER = "me"

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


def add_remote(repo, upstream, origin_head=None):
    """Wire `upstream` in as `origin` and fetch it.

    `origin/HEAD` is then set explicitly, because whether `fetch` creates it
    depends on the git version (newer git does, older git and Apple's do not).
    `None` deletes it, which is the hand-wired-clone state on older git.
    """
    git(repo, "remote", "add", "origin", str(upstream))
    git(repo, "fetch", "-q", "origin")
    if origin_head is None:
        git(repo, "remote", "set-head", "origin", "-d")
    else:
        git(repo, "remote", "set-head", "origin", origin_head)


def make_unborn_repo():
    """An initialised repo with no commit yet, so HEAD points at nothing."""
    path = Path(tempfile.mkdtemp())
    git(path, "init", "-q")
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=path, check=True
    )
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


SKIP_AS_ROOT = unittest.skipIf(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    "root reads regardless of mode bits",
)


def locked_directory(test):
    """A directory with mode 000, restored on cleanup so tempdir removal works.

    `Path.is_file` and `is_dir` raise on EACCES rather than returning False, on
    both 3.9 and 3.13, so anything beneath this directory is a crash probe.
    """
    locked = Path(tempfile.mkdtemp()) / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    test.addCleanup(locked.chmod, 0o755)
    return locked


class Run(unittest.TestCase):
    """`run` never raises: a traceback would leave a caller that parses stdout
    as JSON with nothing to parse."""

    def test_returns_code_and_unstripped_stdout(self):
        code, out = preflight.run([sys.executable, "-c", "print(' x')"], ".")
        self.assertEqual((code, out), (0, " x\n"))

    def test_timeout_maps_to_the_timeout_exit(self):
        code, out = preflight.run(
            [sys.executable, "-c", "import time; time.sleep(5)"], ".", timeout=0.2
        )
        self.assertEqual((code, out), (preflight.TIMEOUT_EXIT, ""))

    def test_missing_executable_maps_to_failure(self):
        self.assertEqual(preflight.run(["definitely-not-a-command-xyz"], "."), (1, ""))

    def test_missing_cwd_maps_to_failure(self):
        missing = Path(tempfile.mkdtemp()) / "gone"
        self.assertEqual(preflight.run(["git", "status"], missing), (1, ""))


def git_unchecked(repo, *args):
    """For git commands expected to stop partway with a non-zero exit."""
    subprocess.run(
        ["git", *GIT_IDENTITY, *args],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_empty_cherry_pick(repo):
    """Leave a cherry-pick stopped with nothing left to commit.

    The picked change is already on main, so the tree is clean and only
    CHERRY_PICK_HEAD records that an operation is in flight.
    """
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "README.md").write_text("changed\n")
    git(repo, "commit", "-q", "-am", "change")
    git(repo, "checkout", "-q", "main")
    git(repo, "cherry-pick", "side")
    git_unchecked(repo, "cherry-pick", "side")


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

    def test_tag_sharing_the_branch_name_does_not_disguise_the_branch(self):
        """`rev-parse --abbrev-ref HEAD` disambiguates to `heads/main` when a
        tag is also called `main`. That no longer equals the default branch,
        so a run sitting on the default branch reads as on a feature branch
        and keeps it, committing straight onto main."""
        repo = make_repo()
        git(repo, "tag", "main")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["current_branch"], "main")
        self.assertTrue(facts["on_default_branch"])

    def test_tag_sharing_a_branch_name_without_a_remote(self):
        repo = make_repo(default_branch="develop")
        git(repo, "tag", "develop")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["default_branch"], "develop")
        self.assertTrue(facts["on_default_branch"])

    def test_detached_head_has_no_current_branch(self):
        repo = make_repo()
        git(repo, "checkout", "-q", "--detach")
        self.assertIsNone(preflight.git_facts(repo)["current_branch"])

    def test_no_operation_in_a_quiet_repo(self):
        self.assertIsNone(preflight.git_facts(make_repo())["operation_in_progress"])

    def test_merge_in_progress_is_reported(self):
        repo = make_repo()
        git(repo, "checkout", "-q", "-b", "side")
        (repo / "side.txt").write_text("side\n")
        git(repo, "add", "side.txt")
        git(repo, "commit", "-q", "-m", "side")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-commit", "--no-ff", "side")
        self.assertEqual(preflight.git_facts(repo)["operation_in_progress"], "merge")

    def test_empty_cherry_pick_reads_clean_but_is_reported(self):
        """Nothing left to commit, so the tree looks clean. The next commit
        would still complete the cherry-pick, and on a kept feature branch a
        stopped merge would turn it into a two-parent merge commit."""
        repo = make_repo()
        start_empty_cherry_pick(repo)
        facts = preflight.git_facts(repo)
        self.assertTrue(facts["tree_clean"])
        self.assertEqual(facts["operation_in_progress"], "cherry-pick")

    def test_operation_in_a_linked_worktree_is_reported(self):
        """In a linked worktree `.git` is a file, not a directory, so state
        files have to be located through git rather than under `cwd/.git`."""
        repo = make_repo()
        linked = Path(tempfile.mkdtemp()) / "linked"
        git(repo, "worktree", "add", "-q", "-b", "wt", str(linked))
        git(linked, "checkout", "-q", "-b", "side")
        (linked / "side.txt").write_text("side\n")
        git(linked, "add", "side.txt")
        git(linked, "commit", "-q", "-m", "side")
        git(linked, "checkout", "-q", "wt")
        git(linked, "merge", "-q", "--no-commit", "--no-ff", "side")
        self.assertEqual(
            preflight.git_facts(linked)["operation_in_progress"], "merge"
        )

    def test_master_repo_detected_as_default(self):
        repo = make_repo(default_branch="master")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["default_branch"], "master")
        self.assertTrue(facts["on_default_branch"])

    def test_remote_default_is_used_when_origin_head_is_unset(self):
        """`git remote add` plus a fetch never sets `origin/HEAD`, so this is the
        ordinary state of a hand-wired clone, not an exotic one. Falling back to
        the current branch there reports a feature branch as the default."""
        upstream = make_repo()
        repo = make_repo(default_branch="trunk")
        add_remote(repo, upstream)
        git(repo, "checkout", "-q", "-b", "feat/x")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["default_branch"], "main")
        self.assertFalse(facts["on_default_branch"])

    def test_unresolvable_default_with_a_remote_is_unknown(self):
        upstream = make_repo(default_branch="develop")
        repo = make_repo(default_branch="trunk")
        add_remote(repo, upstream)
        git(repo, "checkout", "-q", "-b", "feat/x")
        facts = preflight.git_facts(repo)
        self.assertIsNone(facts["default_branch"])
        self.assertFalse(facts["on_default_branch"])

    def test_local_main_is_not_the_default_when_the_remote_lacks_it(self):
        """By the time the local fallback runs, `origin/main` and
        `origin/master` are known absent, so with a remote it can only name a
        branch Phase 1 then fails to find as `origin/<default>`."""
        upstream = make_repo(default_branch="develop")
        repo = make_repo()
        add_remote(repo, upstream)
        facts = preflight.git_facts(repo)
        self.assertIsNone(facts["default_branch"])
        self.assertFalse(facts["on_default_branch"])

    def test_default_branch_containing_a_slash_is_kept_whole(self):
        upstream = make_repo(default_branch="release/x")
        repo = make_repo(default_branch="trunk")
        add_remote(repo, upstream, origin_head="release/x")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["default_branch"], "release/x")

    def test_current_branch_is_default_only_without_a_remote(self):
        repo = make_repo(default_branch="develop")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["default_branch"], "develop")
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

    def test_untracked_file_is_dirty_when_config_hides_untracked(self):
        """`status.showUntrackedFiles=no` can come from user, repo, or system
        config, none of which the script controls. Honouring it would empty the
        status output and let the dirty-tree gate fail open."""
        repo = make_repo()
        git(repo, "config", "status.showUntrackedFiles", "no")
        (repo / "stray.txt").write_text("hidden by config\n")
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["tree_clean"])
        self.assertIn("stray.txt", facts["dirty_paths"])

    def test_dirty_submodule_is_dirty_when_config_ignores_it(self):
        """`submodule.<name>.ignore` hides a modified submodule from status the
        same way, and is just as outside the script's control."""
        inner = make_repo()
        repo = make_repo()
        git(repo, "-c", "protocol.file.allow=always",
            "submodule", "add", "-q", str(inner), "sub")
        git(repo, "commit", "-q", "-m", "add submodule")
        git(repo, "config", "submodule.sub.ignore", "all")
        (repo / "sub" / "README.md").write_text("changed inside\n")
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["tree_clean"])
        self.assertIn("sub", facts["dirty_paths"])

    def test_unicode_line_separator_in_a_name_is_still_dirty(self):
        """`str.splitlines` also breaks on U+0085 and similar, which git does
        not treat as line ends. With `core.quotePath=false` such a name reaches
        the parser raw, splits into fragments too short to keep, and the tree
        reads as clean."""
        repo = make_repo()
        git(repo, "config", "core.quotePath", "false")
        (repo / "\u0085x").write_text("odd name\n")
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["tree_clean"])
        self.assertIn("\u0085x", facts["dirty_paths"])

    def test_staged_rename_reports_the_new_path(self):
        repo = make_repo()
        git(repo, "mv", "README.md", "RENAMED.md")
        facts = preflight.git_facts(repo)
        self.assertEqual(facts["dirty_paths"], ["RENAMED.md"])

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

    def test_detached_head_is_reported(self):
        """`rev-parse --abbrev-ref HEAD` prints the literal "HEAD" when detached,
        which reads as an ordinary branch name. Left unflagged, the run commits
        onto a detached HEAD and the work is orphaned."""
        repo = make_repo()
        git(repo, "checkout", "-q", "--detach")
        facts = preflight.git_facts(repo)
        self.assertTrue(facts["detached_head"])

    def test_unborn_branch_is_reported(self):
        """An unborn HEAD also prints "HEAD", and the default-branch fallback
        then returns that same string, making on_default_branch trivially true."""
        repo = make_unborn_repo()
        facts = preflight.git_facts(repo)
        self.assertTrue(facts["unborn_branch"])
        self.assertNotEqual(facts["default_branch"], "HEAD")
        self.assertFalse(facts["on_default_branch"])

    def test_ordinary_repo_is_neither_detached_nor_unborn(self):
        repo = make_repo()
        facts = preflight.git_facts(repo)
        self.assertFalse(facts["detached_head"])
        self.assertFalse(facts["unborn_branch"])

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

    def test_anchored_patterns_match_only_at_the_root(self):
        """A leading `/` anchors a CODEOWNERS rule to the repository root.
        Stripping it before deciding which branch to take sends anchored rules
        down the basename path, which names owners for files they do not own."""
        repo = make_repo()
        (repo / "CODEOWNERS").write_text(
            "/*.md @root-glob\n"
            "/README.md @root-literal\n"
        )
        self.assertEqual(
            preflight.codeowners_for(repo, ["docs/sub/file.md"])["owners"], []
        )
        self.assertEqual(
            preflight.codeowners_for(repo, ["docs/README.md"])["owners"], []
        )
        self.assertEqual(
            preflight.codeowners_for(repo, ["README.md"])["owners"], ["@root-literal"]
        )
        self.assertEqual(
            preflight.codeowners_for(repo, ["CHANGELOG.md"])["owners"], ["@root-glob"]
        )

    def test_anchored_directory_still_matches_below_itself(self):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text("/docs @docs-team\n")
        result = preflight.codeowners_for(repo, ["docs/sub/file.md"])
        self.assertEqual(result["owners"], ["@docs-team"])

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

    def owners(self, rules, path):
        repo = make_repo()
        (repo / "CODEOWNERS").write_text(rules)
        return preflight.codeowners_for(repo, [path])["owners"]

    def test_unanchored_directory_matches_at_any_depth(self):
        """GitHub's `apps/` example owns an `apps` directory anywhere. Missing
        a nested match is not harmless under last-match-wins: the earlier
        catch-all wins instead, and the wrong team is asked to review."""
        rules = "* @default\ndocs/ @docs\n"
        self.assertEqual(self.owners(rules, "src/docs/a.md"), ["@docs"])

    def test_double_star_matches_a_directory_at_any_depth(self):
        rules = "* @default\n**/logs @logs\n"
        self.assertEqual(self.owners(rules, "x/logs/y.txt"), ["@logs"])
        self.assertEqual(self.owners(rules, "logs/y.txt"), ["@logs"])

    def test_bare_name_matches_a_directory_as_well_as_a_file(self):
        rules = "* @default\nbuild @build\n"
        self.assertEqual(self.owners(rules, "build/out.js"), ["@build"])
        self.assertEqual(self.owners(rules, "src/build/out.js"), ["@build"])
        self.assertEqual(self.owners(rules, "tools/build"), ["@build"])

    def test_inner_slash_anchors_the_pattern(self):
        """Under gitignore rules a slash before the end anchors a pattern to
        the root, so `docs/api/` must not claim `src/docs/api/`."""
        rules = "* @default\ndocs/api/ @api\n"
        self.assertEqual(self.owners(rules, "docs/api/x.md"), ["@api"])
        self.assertEqual(self.owners(rules, "src/docs/api/x.md"), ["@default"])

    def test_rule_without_owners_clears_ownership(self):
        """GitHub's own example: an owner-less `/apps/github` leaves that
        directory unowned. Skipping the line hands it to the rule above."""
        rules = "/apps/ @octocat\n/apps/github\n"
        self.assertEqual(self.owners(rules, "apps/github/x.js"), [])
        self.assertEqual(self.owners(rules, "apps/other/x.js"), ["@octocat"])

    def test_trailing_star_does_not_claim_nested_files(self):
        """GitHub's own example: `docs/*` matches `docs/getting-started.md` but
        not `docs/build-app/troubleshooting.md`. Treating the matched directory
        `docs/build-app` as owning its contents hands nested docs to the wrong
        team under last-match-wins."""
        rules = "* @default\ndocs/* @docs\n"
        self.assertEqual(self.owners(rules, "docs/getting-started.md"), ["@docs"])
        self.assertEqual(
            self.owners(rules, "docs/build-app/troubleshooting.md"), ["@default"]
        )

    def test_root_star_claims_only_root_files(self):
        rules = "* @default\n/* @root\n"
        self.assertEqual(self.owners(rules, "README.md"), ["@root"])
        self.assertEqual(self.owners(rules, "src/x.py"), ["@default"])

    def test_partial_wildcard_directory_still_claims_its_contents(self):
        rules = "* @default\npackages/app-* @apps\n"
        self.assertEqual(self.owners(rules, "packages/app-web/src/i.ts"), ["@apps"])

    def test_brackets_are_not_a_character_range(self):
        rules = "* @default\nfile[ab].md @range\n"
        self.assertEqual(self.owners(rules, "filea.md"), ["@default"])

    def test_negation_is_not_supported(self):
        rules = "*.md @docs\n!README.md @nobody\n"
        self.assertEqual(self.owners(rules, "README.md"), ["@docs"])

    def test_matching_is_case_sensitive(self):
        rules = "* @default\n*.MD @shouty\n"
        self.assertEqual(self.owners(rules, "README.md"), ["@default"])

    def test_undecodable_file_reports_unreadable_rather_than_no_owners(self):
        """An empty owner list must mean "no rule matched", never "the file
        could not be read". Collapsing the two is a silent zero: the run would
        report nobody owns the code when it simply failed to look."""
        repo = make_repo()
        (repo / "CODEOWNERS").write_bytes(b"\xff\xfe* @default-owner\n")
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertFalse(result["readable"])
        self.assertEqual(result["owners"], [])

    @SKIP_AS_ROOT
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

    @SKIP_AS_ROOT
    def test_unsearchable_location_reports_unreadable_rather_than_raising(self):
        """When a CODEOWNERS location cannot even be probed, whether a file
        exists there is unknown, which is not the same as there being none."""
        repo = make_repo()
        github = repo / ".github"
        github.mkdir()
        (github / "CODEOWNERS").write_text("* @default-owner\n")
        github.chmod(0o000)
        self.addCleanup(github.chmod, 0o755)
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertFalse(result["readable"])

    def test_absent_file_counts_as_readable(self):
        """No CODEOWNERS is a known state, not a failure to read one."""
        repo = make_repo()
        result = preflight.codeowners_for(repo, ["skills/pickup/SKILL.md"])
        self.assertTrue(result["readable"])


class GhAuthState(unittest.TestCase):
    def auth_args(self, repo, environment=None, ssh_config=None):
        """The `gh auth status` argv, with git real and gh and ssh stubbed.

        `ssh` is always stubbed: `ssh -G` reads the config under the passwd
        home, which the module's empty `HOME` does not hide. `ssh_config` is
        what `ssh -G` prints; None makes it fail.
        """
        real_run = preflight.run
        self.calls = []

        def fake_run(args, cwd, timeout=None):
            self.calls.append(args)
            if args[0] == "gh":
                return 0, ""
            if args[0] == "ssh":
                return (0, ssh_config) if ssh_config is not None else (255, "")
            return real_run(args, cwd, timeout)

        with mock.patch.dict(os.environ, environment or {}), \
             mock.patch.object(preflight, "run", side_effect=fake_run):
            preflight.gh_auth_state(repo)
        return next(
            call for call in self.calls if call[:3] == ["gh", "auth", "status"]
        )

    def hostname_in(self, args):
        return args[args.index("--hostname") + 1]

    def test_ssh_alias_resolves_to_its_real_host(self):
        """gh translates an SSH alias through `ssh -G` before choosing a host,
        so `git@github-work:...` talks to github.com. Scoping auth to the alias
        reports a working login as unauthenticated and blocks every run."""
        repo = make_repo()
        git(repo, "remote", "add", "origin", "git@github-work:org/repo.git")
        args = self.auth_args(
            repo, ssh_config="user git\nhostname github.com\nport 22\n"
        )
        self.assertEqual(self.hostname_in(args), "github.com")

    def test_ssh_over_port_443_maps_to_github_com(self):
        """GitHub's documented port-443 setup uses `ssh.github.com`, which gh
        maps back to github.com; no alias is involved."""
        repo = make_repo()
        git(repo, "remote", "add", "origin",
            "ssh://git@ssh.github.com:443/org/repo.git")
        args = self.auth_args(repo, ssh_config="hostname ssh.github.com\n")
        self.assertEqual(self.hostname_in(args), "github.com")

    def test_failed_ssh_lookup_keeps_the_parsed_host(self):
        repo = make_repo()
        git(repo, "remote", "add", "origin", "git@ghe.example.com:org/repo.git")
        args = self.auth_args(repo, ssh_config=None)
        self.assertEqual(self.hostname_in(args), "ghe.example.com")

    def test_https_remote_does_not_consult_ssh(self):
        repo = make_repo()
        git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
        self.auth_args(repo, ssh_config="hostname elsewhere.example\n")
        self.assertFalse([call for call in self.calls if call[0] == "ssh"])

    def test_scoped_to_the_remote_host_and_active_account(self):
        """Unscoped, `gh auth status` exits 1 when any account on any host has
        a problem, so a stale second login blocks every run. Only the account
        the run will actually use matters."""
        repo = make_repo()
        git(repo, "remote", "add", "origin", "git@ghe.example.com:org/repo.git")
        args = self.auth_args(repo)
        self.assertIn("--active", args)
        self.assertEqual(args[args.index("--hostname") + 1], "ghe.example.com")

    def test_https_remote_host_is_parsed(self):
        repo = make_repo()
        git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
        args = self.auth_args(repo)
        self.assertEqual(args[args.index("--hostname") + 1], "github.com")

    def test_gh_host_overrides_the_remote(self):
        repo = make_repo()
        git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
        args = self.auth_args(repo, {"GH_HOST": "ghe.example.com"})
        self.assertEqual(args[args.index("--hostname") + 1], "ghe.example.com")

    def test_no_remote_defaults_to_github_com(self):
        repo = make_repo()
        args = self.auth_args(repo)
        self.assertEqual(args[args.index("--hostname") + 1], "github.com")

    def test_exit_codes_map_to_states(self):
        for code, state in ((0, "ok"), (1, "unauthenticated"),
                            (preflight.TIMEOUT_EXIT, "timeout")):
            with self.subTest(code=code), \
                 mock.patch.object(preflight, "run", return_value=(code, "")):
                self.assertEqual(preflight.gh_auth_state("."), state)


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


def make_pr(number, body=None, login=VIEWER, head="feat/other", fork=False):
    return {
        "number": number,
        "body": body,
        "author": {"login": login},
        "headRefName": head,
        "isCrossRepository": fork,
    }


def citing(handoff_name):
    return "Picked up from `{}`.".format(handoff_name)


class FindRunPrs(unittest.TestCase):
    """Resume detection. Keyed on the handoff document a PR body cites, not on
    the branch name, so a run resumes even from a differently named branch."""

    HANDOFF = "/tmp/scratch/handoff-featurecard-layout.md"
    NAME = "handoff-featurecard-layout.md"

    def numbers(self, prs):
        return [pr["number"] for pr in preflight.find_run_prs(prs, self.HANDOFF, VIEWER)]

    def test_no_open_prs(self):
        self.assertEqual(self.numbers([]), [])

    def test_body_citing_the_handoff_matches(self):
        self.assertEqual(self.numbers([make_pr(7, citing(self.NAME))]), [7])

    def test_unrelated_prs_do_not_match(self):
        prs = [make_pr(4, "unrelated work"), make_pr(5, citing("handoff-other.md"))]
        self.assertEqual(self.numbers(prs), [])

    def test_a_name_containing_the_basename_does_not_match(self):
        """A substring test lets `old-handoff-featurecard-layout.md` claim the
        run as well as the real PR."""
        prs = [make_pr(5, citing("old-" + self.NAME)), make_pr(9, citing(self.NAME))]
        self.assertEqual(self.numbers(prs), [9])

    def test_a_bare_mention_is_not_a_citation(self):
        self.assertEqual(self.numbers([make_pr(5, "see " + self.NAME)]), [])

    def test_another_authors_pr_is_never_adopted(self):
        """The mandate forbids touching any pull request but the run's own. A
        colleague's PR that happens to cite the same name is not one."""
        prs = [make_pr(5, citing(self.NAME), login="someone")]
        self.assertEqual(self.numbers(prs), [])

    def test_every_match_is_returned_in_number_order(self):
        prs = [make_pr(9, citing(self.NAME)), make_pr(3, citing(self.NAME))]
        self.assertEqual(self.numbers(prs), [3, 9])

    def test_missing_body_is_tolerated(self):
        self.assertEqual(self.numbers([{"number": 2}, make_pr(3, None)]), [])


class FindBranchPr(unittest.TestCase):
    def test_same_repo_pr_on_the_branch_is_found(self):
        prs = [make_pr(4, head="feat/thing")]
        self.assertEqual(preflight.find_branch_pr(prs, "feat/thing")["number"], 4)

    def test_fork_pr_sharing_the_branch_name_is_ignored(self):
        """Fork heads routinely reuse names like `patch-1` or `main`; only a
        branch in this repository is the one the run would push to."""
        prs = [make_pr(4, head="feat/thing", fork=True)]
        self.assertIsNone(preflight.find_branch_pr(prs, "feat/thing"))

    def test_no_pr_on_the_branch(self):
        prs = [make_pr(4, head="feat/other")]
        self.assertIsNone(preflight.find_branch_pr(prs, "feat/thing"))


class Blockers(unittest.TestCase):
    """Only mechanically determinable blockers belong here. Semantic ones (a doc
    contradicting its issue, an irreversible change) stay model judgment in
    TRIAGE.md; this script must never appear to have ruled on them."""

    def collect(self, repo, handoff, prs=None, authed="ok"):
        with mock.patch.object(preflight, "gh_open_prs", return_value=prs or []), \
             mock.patch.object(preflight, "gh_auth_state", return_value=authed), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
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

    def test_missing_cwd_reports_its_own_cause(self):
        """An unreachable directory and a real directory outside any repo fail
        the same git call. Reporting both as "not a git repository" sends the
        reader looking for the wrong problem."""
        missing = Path(tempfile.mkdtemp()) / "gone"
        result = self.collect(missing, make_handoff_doc())
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("cwd-unreadable", codes)
        self.assertNotIn("not-a-git-repo", codes)

    @SKIP_AS_ROOT
    def test_handoff_doc_behind_a_locked_directory_is_unreadable(self):
        repo = make_repo()
        doc = str(locked_directory(self) / "handoff.md")
        result = self.collect(repo, doc)
        self.assertIn(
            "handoff-doc-unreadable", [b["code"] for b in result["blockers"]]
        )

    @SKIP_AS_ROOT
    def test_cwd_behind_a_locked_directory_is_unreadable(self):
        cwd = locked_directory(self) / "repo"
        result = self.collect(cwd, make_handoff_doc())
        self.assertIn("cwd-unreadable", [b["code"] for b in result["blockers"]])

    def test_feature_branch_with_an_unrelated_pr_blocks(self):
        """"On a feature branch already, keep it" would push this run's commits
        onto whatever PR that branch already carries."""
        repo = make_repo()
        git(repo, "checkout", "-q", "-b", "feat/thing")
        prs = [make_pr(4, "someone else's work", head="feat/thing")]
        result = self.collect(repo, make_handoff_doc(), prs=prs)
        self.assertIn("branch-has-other-pr", [b["code"] for b in result["blockers"]])
        self.assertEqual(result["current_branch_pr"]["number"], 4)

    def test_feature_branch_carrying_the_run_pr_does_not_block(self):
        repo = make_repo()
        git(repo, "checkout", "-q", "-b", "feat/thing")
        doc = make_handoff_doc()
        prs = [make_pr(4, citing(os.path.basename(doc)), head="feat/thing")]
        result = self.collect(repo, doc, prs=prs)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["existing_pr"]["number"], 4)

    def test_several_run_prs_citing_one_handoff_block(self):
        """Two of the viewer's PRs citing one handoff name means either an
        abandoned run or two handoffs sharing a basename. Silently picking one
        resumes the wrong run half the time."""
        repo = make_repo()
        doc = make_handoff_doc()
        cite = citing(os.path.basename(doc))
        result = self.collect(repo, doc, prs=[make_pr(3, cite), make_pr(9, cite)])
        self.assertIn(
            "pickup-run-ambiguous", [b["code"] for b in result["blockers"]]
        )
        self.assertIsNone(result["existing_pr"])

    def test_unknown_viewer_blocks(self):
        """Without the authenticated login there is no telling the run's own
        PR from anyone else's, so a resume cannot be ruled out."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=[]), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=None):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIn("gh-viewer-unknown", [b["code"] for b in result["blockers"]])

    def test_operation_in_progress_blocks_even_on_a_clean_tree(self):
        repo = make_repo()
        start_empty_cherry_pick(repo)
        result = self.collect(repo, make_handoff_doc())
        self.assertIn(
            "operation-in-progress", [b["code"] for b in result["blockers"]]
        )

    def test_unknown_default_branch_blocks(self):
        """Phase 1 branches from the default branch. A guess there either
        builds on the wrong base or abandons the branch the handoff came from."""
        upstream = make_repo(default_branch="develop")
        repo = make_repo(default_branch="trunk")
        add_remote(repo, upstream)
        result = self.collect(repo, make_handoff_doc())
        self.assertIn(
            "default-branch-unknown", [b["code"] for b in result["blockers"]]
        )

    def test_unauthenticated_gh_blocks(self):
        repo = make_repo()
        result = self.collect(repo, make_handoff_doc(), authed="unauthenticated")
        self.assertIn("gh-unauthenticated", [b["code"] for b in result["blockers"]])

    def test_default_branch_is_not_a_blocker(self):
        """Sitting on main is the expected starting state; the skill branches
        from it. Blocking here would reject the common case."""
        repo = make_repo()
        result = self.collect(repo, make_handoff_doc())
        self.assertNotIn("on-default-branch", [b["code"] for b in result["blockers"]])
        self.assertTrue(result["on_default_branch"])

    def blocker_scenarios(self):
        """One state per blocker code, each producing that code."""
        def repo_with(*steps):
            repo = make_repo()
            for step in steps:
                step(repo)
            return repo

        def failing_status(args, cwd, timeout=None):
            if "status" in args:
                return 1, ""
            return REAL_RUN(args, cwd, timeout)

        on_feature = lambda repo: git(repo, "checkout", "-q", "-b", "feat/thing")
        doc = make_handoff_doc()
        upstream = make_repo(default_branch="develop")
        yield "cwd-unreadable", Path(tempfile.mkdtemp()) / "gone", doc, {}
        yield "not-a-git-repo", Path(tempfile.mkdtemp()), doc, {}
        yield "git-status-failed", repo_with(), doc, {"run": failing_status}
        yield "unborn-branch", make_unborn_repo(), doc, {}
        yield "detached-head", repo_with(
            lambda repo: git(repo, "checkout", "-q", "--detach")
        ), doc, {}
        yield "default-branch-unknown", repo_with(
            lambda repo: git(repo, "branch", "-q", "-m", "trunk"),
            lambda repo: add_remote(repo, upstream),
        ), doc, {}
        yield "operation-in-progress", repo_with(start_empty_cherry_pick), doc, {}
        yield "dirty-tree", repo_with(
            lambda repo: (repo / "stray.txt").write_text("x\n")
        ), doc, {}
        yield "handoff-doc-unreadable", repo_with(), "/nonexistent/h.md", {}
        yield "gh-timeout", repo_with(), doc, {"authed": "timeout"}
        yield "gh-unauthenticated", repo_with(), doc, {"authed": "unauthenticated"}
        yield "pr-lookup-truncated", repo_with(), doc, {
            "prs": [make_pr(n) for n in range(preflight.PR_LIST_LIMIT)]
        }
        yield "pr-lookup-failed", repo_with(), doc, {"prs": None}
        yield "gh-viewer-unknown", repo_with(), doc, {"viewer": None}
        cite = citing(os.path.basename(doc))
        yield "pickup-run-ambiguous", repo_with(), doc, {
            "prs": [make_pr(3, cite), make_pr(9, cite)]
        }
        yield "branch-has-other-pr", repo_with(on_feature), doc, {
            "prs": [make_pr(4, head="feat/thing")]
        }

    def test_every_blocker_code_is_produced_and_carries_a_detail(self):
        """A blocker without a detail tells the reader that something is wrong
        but not what. Scenarios are checked against every code in the source,
        so a new blocker cannot ship without one."""
        covered = set()
        for code, cwd, doc, options in self.blocker_scenarios():
            with self.subTest(code=code), \
                 mock.patch.object(preflight, "run",
                                   side_effect=options.get("run", REAL_RUN)), \
                 mock.patch.object(preflight, "gh_open_prs",
                                   return_value=options.get("prs", [])), \
                 mock.patch.object(preflight, "gh_auth_state",
                                   return_value=options.get("authed", "ok")), \
                 mock.patch.object(preflight, "gh_viewer",
                                   return_value=options.get("viewer", VIEWER)):
                result = preflight.collect(cwd, doc)
                blockers = {b["code"]: b for b in result["blockers"]}
                self.assertIn(code, blockers)
                self.assertTrue(blockers[code].get("detail"))
                covered.add(code)
        emitted = set(re.findall(r'"code": "([a-z-]+)"', SCRIPT.read_text()))
        # The crash blocker is emitted by main rather than collect; Cli covers it.
        self.assertEqual(covered, emitted - {"preflight-crashed"})


class Resume(unittest.TestCase):
    def test_existing_pr_is_surfaced(self):
        repo = make_repo()
        doc = make_handoff_doc()
        prs = [make_pr(11, citing("handoff-thing.md"), head="feat/thing")]
        with mock.patch.object(preflight, "gh_open_prs", return_value=prs), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
            result = preflight.collect(repo, doc)
        self.assertEqual(result["existing_pr"]["number"], 11)

    def test_absent_pr_is_null(self):
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=[]), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
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
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIn("git-status-failed", [b["code"] for b in result["blockers"]])

    def test_saturated_lookup_blocks(self):
        """A full page means the window may have cut off the run's own PR.
        `gh pr list` returns newest first, so a stale resume against a busy repo
        is the case that silently opens a duplicate."""
        repo = make_repo()
        page = [{"number": n, "body": ""} for n in range(preflight.PR_LIST_LIMIT)]
        with mock.patch.object(preflight, "gh_open_prs", return_value=page), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIn("pr-lookup-truncated", [b["code"] for b in result["blockers"]])

    def test_short_page_does_not_block(self):
        repo = make_repo()
        page = [{"number": 1, "body": ""}]
        with mock.patch.object(preflight, "gh_open_prs", return_value=page), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertNotIn(
            "pr-lookup-truncated", [b["code"] for b in result["blockers"]]
        )

    def test_gh_timeout_is_not_reported_as_unauthenticated(self):
        """A hung network call and a missing credential are different problems
        with different remedies; one label for both sends the reader wrong."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_auth_state", return_value="timeout"):
            result = preflight.collect(repo, make_handoff_doc())
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("gh-timeout", codes)
        self.assertNotIn("gh-unauthenticated", codes)

    def test_failed_lookup_blocks_rather_than_reporting_no_pr(self):
        """Proceeding on a failed lookup would open a second PR for a run that
        already has one, unattended and outward-facing."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=None), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertIn("pr-lookup-failed", [b["code"] for b in result["blockers"]])
        self.assertIsNone(result["existing_pr"])

    def test_genuinely_empty_lookup_does_not_block(self):
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs", return_value=[]), \
             mock.patch.object(preflight, "gh_auth_state", return_value="ok"), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER):
            result = preflight.collect(repo, make_handoff_doc())
        self.assertNotIn("pr-lookup-failed", [b["code"] for b in result["blockers"]])

    def test_unauthenticated_gh_does_not_also_report_lookup_failure(self):
        """One root cause, one blocker. The gh-unauthenticated blocker already
        explains why no lookup happened."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_auth_state", return_value="unauthenticated"):
            result = preflight.collect(repo, make_handoff_doc())
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("gh-unauthenticated", codes)
        self.assertNotIn("pr-lookup-failed", codes)

    def test_pr_lookup_skipped_when_gh_unauthenticated(self):
        """No auth means no reliable answer about existing PRs. Reporting null
        as though the lookup succeeded would let a resume silently restart."""
        repo = make_repo()
        with mock.patch.object(preflight, "gh_open_prs") as lookup, \
             mock.patch.object(preflight, "gh_auth_state", return_value="unauthenticated"):
            result = preflight.collect(repo, make_handoff_doc())
        lookup.assert_not_called()
        self.assertIsNone(result["existing_pr"])


class Cli(unittest.TestCase):
    def run_main(self, argv, prs=None, authed="ok"):
        out = []
        with mock.patch.object(preflight, "gh_open_prs", return_value=prs or []), \
             mock.patch.object(preflight, "gh_auth_state", return_value=authed), \
             mock.patch.object(preflight, "gh_viewer", return_value=VIEWER), \
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

    def test_paths_resolve_owners_end_to_end(self):
        """The `--paths` route is what Phase 5 uses to name a reviewer, and it
        is the one place the CODEOWNERS matcher is reached through `collect`."""
        repo = make_repo()
        (repo / ".github").mkdir()
        (repo / ".github" / "CODEOWNERS").write_text("skills/ @skills-team\n")
        git(repo, "add", ".github/CODEOWNERS")
        git(repo, "commit", "-q", "-m", "owners")
        code, output = self.run_main([
            "--handoff-doc", make_handoff_doc(),
            "--cwd", str(repo),
            "--paths", "skills/pickup/SKILL.md",
        ])
        self.assertEqual(code, preflight.CLEAR)
        parsed = json.loads(output)
        self.assertEqual(parsed["codeowners"]["owners"], ["@skills-team"])
        self.assertTrue(parsed["codeowners"]["readable"])

    def test_crash_exits_distinctly_and_still_emits_json(self):
        """An uncaught exception exits 1 with empty stdout, which is the blocked
        exit with nothing to read. The caller then hunts for blockers in an
        empty string instead of learning the gate itself broke."""
        with mock.patch.object(preflight, "collect", side_effect=RuntimeError("boom")):
            code, output = self.run_main(["--handoff-doc", "x.md"])
        self.assertEqual(code, preflight.CRASHED)
        self.assertNotIn(code, (preflight.CLEAR, preflight.BLOCKED))
        parsed = json.loads(output)
        self.assertEqual(
            [b["code"] for b in parsed["blockers"]], ["preflight-crashed"]
        )
        self.assertIn("boom", parsed["blockers"][0]["detail"])

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
