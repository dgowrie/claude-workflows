#!/usr/bin/env python3
"""Report the mechanically checkable preconditions for a `/pickup` run.

Usage: preflight.py --handoff-doc <path> [--cwd <dir>] [--paths <path>...]

Prints one JSON object of facts on stdout and exits:

    0  clear    no mechanical blocker; the run may proceed to triage
    1  blocked  at least one blocker; `blockers` says which
    2  usage    the arguments were wrong; no facts were gathered

The point of this script is that `/pickup` runs unattended. A gate that depends
on the model remembering to check is not a gate, so every precondition that can
be settled by looking rather than by reasoning is settled here, once, and
reported as a fact.

The converse bound matters just as much: only mechanically determinable blockers
belong in `blockers`. Whether a handoff document contradicts its linked issue, or
whether a change is irreversible, is model judgment and lives in TRIAGE.md. This
script must never look like it has ruled on those.

Known bounds:

* CODEOWNERS support covers `*`, basename globs (`*.md`), directory prefixes
  (`skills/`), and anchored paths, with last-match-wins, and wildcards stay
  inside one path segment as CODEOWNERS specifies. It does not implement
  negation or the full gitignore pattern grammar. An unmatched path contributes
  no owners rather than a wrong one, and an unreadable CODEOWNERS reports
  `readable: false` rather than an empty owner list.
* The default branch is read from `origin/HEAD` when a remote is configured, and
  otherwise inferred from whether `main` or `master` exists locally. A repo whose
  default branch is neither, and which has no remote, reports its current branch.
* Resume detection matches the handoff document's basename against open PR
  bodies. Two handoff documents sharing a basename across a repo would collide;
  the lowest-numbered match wins, so the collision resolves to a stable answer
  rather than an arbitrary one.
* The open-PR listing reads one window of `PR_LIST_LIMIT` entries, newest
  first. A repo busy enough to fill it reports `pr-lookup-truncated` rather than
  a possibly incomplete answer, since a resume that cannot see its own pull
  request opens a duplicate.
* Only the `gh` calls carry a deadline. `git status` may legitimately run long
  on a large repo with a cold cache, and timing it out would convert a benign
  state into a blocker.

Run this OUTSIDE the command sandbox. `gh auth status` exits 1 in the sandbox
because the credential keyring is unreachable, which reports a working install as
`gh-unauthenticated` and blocks every run. The `gh` calls the rest of the
pipeline makes have the same constraint, so this is the existing rule for `gh`
rather than a new one.
"""
import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

CLEAR, BLOCKED, USAGE_ERROR = 0, 1, 2

# Conventional shell exit status for a timed-out command, reused here so a
# caller can tell a hang apart from an ordinary failure.
TIMEOUT_EXIT = 124

# `gh pr list` pages, and a full page means the window may have cut off the
# run's own PR. Set high enough that saturation signals a pathological repo
# rather than an ordinary busy one: a 634-PR repo returns in about 3 seconds.
PR_LIST_LIMIT = 1000

# Only the network-bound `gh` calls get a deadline. `git status` can legitimately
# take a long time on a large repo with a cold cache, and timing it out would
# turn a benign state into a blocker.
GH_TIMEOUT_SECONDS = 30

CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def run(args, cwd, timeout=None):
    """Run a command, returning (returncode, raw stdout). Never raises.

    Deliberately unstripped. `git status --porcelain` encodes the status in the
    first two columns, so leading whitespace is data; stripping it here silently
    shifted every reported path by one character. Callers wanting a scalar strip
    at the call site.

    `subprocess.TimeoutExpired` is a `SubprocessError`, not an `OSError`, so it
    needs naming explicitly; without it a deadline would convert a hang into an
    uncaught traceback, which is worse for a caller that parses stdout as JSON
    on both the clear and the blocked exit.
    """
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return TIMEOUT_EXIT, ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout


def _default_branch(cwd):
    code, out = run(
        ["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd
    )
    if code == 0 and out.strip():
        return out.strip().rsplit("/", 1)[-1]
    for candidate in ("main", "master"):
        code, _ = run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + candidate], cwd
        )
        if code == 0:
            return candidate
    code, current = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    current = current.strip()
    # A detached or unborn HEAD prints the literal "HEAD", which is not a branch
    # name. Returning it would make `on_default_branch` compare a string to
    # itself and come out true.
    if code != 0 or not current or current == "HEAD":
        return None
    return current


def _dirty_paths(porcelain):
    """Paths from `git status --porcelain`, including untracked.

    Untracked files count as dirty. An unattended run must not bulldoze work
    whose origin it cannot establish, and untracked files are precisely the case
    where it has the least idea what it would be destroying.
    """
    paths = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        # Renames arrive as "old -> new"; the destination is what exists now.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def git_facts(cwd):
    code, root = run(["git", "rev-parse", "--show-toplevel"], cwd)
    root = root.strip()
    if code != 0 or not root:
        return {
            "repo_root": None,
            "current_branch": None,
            "default_branch": None,
            "on_default_branch": False,
            "tree_clean": False,
            "status_ok": False,
            "detached_head": False,
            "unborn_branch": False,
            "dirty_paths": [],
        }

    _, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    branch = branch.strip()
    # A failed `git status` prints nothing, which is indistinguishable from a
    # clean tree. Keeping the return code is what stops the dirty-tree gate
    # from failing open on an unknown tree state.
    status_code, porcelain = run(["git", "status", "--porcelain"], cwd)
    status_ok = status_code == 0
    default = _default_branch(cwd)
    dirty = _dirty_paths(porcelain)

    # Both states print "HEAD" from `rev-parse --abbrev-ref`, so neither is
    # visible in the branch name alone. `symbolic-ref` fails only when HEAD is
    # detached; `rev-parse --verify HEAD` fails only before the first commit.
    symbolic_code, _ = run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd)
    verify_code, _ = run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd)
    unborn = verify_code != 0
    detached = symbolic_code != 0 and not unborn

    return {
        "repo_root": root,
        "current_branch": branch or None,
        "default_branch": default,
        "on_default_branch": bool(default) and branch == default,
        "tree_clean": status_ok and not dirty,
        "status_ok": status_ok,
        "detached_head": detached,
        "unborn_branch": unborn,
        "dirty_paths": dirty,
    }


def _matches_per_segment(pattern, path):
    """Glob each path segment separately.

    `fnmatch` on the whole path lets `*` span separators, so `docs/*.md` would
    match `docs/sub/file.md` and name the wrong owners. Comparing segment by
    segment confines each wildcard to its own segment.
    """
    pattern_parts = pattern.split("/")
    path_parts = path.split("/")
    if len(pattern_parts) != len(path_parts):
        return False
    return all(
        fnmatch.fnmatch(path_part, pattern_part)
        for pattern_part, path_part in zip(pattern_parts, path_parts)
    )


def _codeowners_matches(pattern, path):
    if pattern == "*":
        return True
    # A leading `/` anchors the rule to the repository root. Stripping it before
    # choosing a branch sends anchored rules down the basename path, which then
    # claims files anywhere in the tree: `/README.md` would own
    # `docs/README.md`. Capture the anchor before it is discarded.
    anchored = pattern.startswith("/")
    cleaned = pattern.lstrip("/")
    if cleaned.endswith("/"):
        return path.startswith(cleaned)
    if "/" not in cleaned and not anchored:
        return fnmatch.fnmatch(os.path.basename(path), cleaned)
    if path.startswith(cleaned + "/"):
        return True
    return _matches_per_segment(cleaned, path)


def codeowners_for(repo_root, paths):
    """Owners of `paths`, unioned, using last-match-wins per path.

    `readable` separates "no rule matched" from "the file could not be read".
    Collapsing the two into an empty owner list is a silent zero: the run would
    report that nobody owns the code when it had simply failed to look.
    """
    root = Path(repo_root)
    location = None
    for candidate in CODEOWNERS_LOCATIONS:
        if (root / candidate).is_file():
            location = candidate
            break
    if location is None:
        return {"file": None, "owners": [], "readable": True}

    try:
        # Pin the encoding. Defaulting to the platform's preferred encoding
        # makes the unreadable branch depend on the host locale: on a latin-1
        # host a corrupt file decodes to mojibake, no error is raised, and the
        # result is the silent zero `readable` exists to prevent.
        contents = (root / location).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"file": str(root / location), "owners": [], "readable": False}

    rules = []
    for line in contents.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        rules.append((fields[0], fields[1:]))

    owners = []
    for path in paths or []:
        winner = None
        for pattern, pattern_owners in rules:
            if _codeowners_matches(pattern, path):
                winner = pattern_owners
        for owner in winner or []:
            if owner not in owners:
                owners.append(owner)

    return {"file": str(root / location), "owners": owners, "readable": True}


def gh_auth_state(cwd):
    """One of "ok", "timeout", or "unauthenticated".

    A hung network call and a missing credential need different remedies, so
    reporting both as unauthenticated sends the reader after the wrong problem.
    """
    code, _ = run(["gh", "auth", "status"], cwd, timeout=GH_TIMEOUT_SECONDS)
    if code == TIMEOUT_EXIT:
        return "timeout"
    return "ok" if code == 0 else "unauthenticated"


def gh_open_prs(cwd):
    """Open PRs, or None when the lookup failed.

    The distinction carries weight downstream: a resume that cannot see its own
    pull request opens a duplicate one, unattended. `gh pr list --json` prints
    `[]` for a repo with nothing open, so silence means failure rather than
    emptiness.
    """
    code, out = run(
        [
            "gh", "pr", "list",
            "--state", "open",
            "--json", "number,url,headRefName,body",
            "--limit", str(PR_LIST_LIMIT),
        ],
        cwd,
        timeout=GH_TIMEOUT_SECONDS,
    )
    if code != 0 or not out.strip():
        return None
    try:
        parsed = json.loads(out)
    except ValueError:
        return None
    return parsed if isinstance(parsed, list) else None


def find_run_pr(prs, handoff_doc):
    """The open PR belonging to this run, or None.

    Keyed on the handoff document a PR body cites rather than on the branch name,
    so a run resumes even when the branch was renamed between sessions.
    """
    needle = os.path.basename(handoff_doc)
    matches = [pr for pr in prs if needle in (pr.get("body") or "")]
    if not matches:
        return None
    return sorted(matches, key=lambda pr: pr.get("number", 0))[0]


def collect(cwd, handoff_doc, paths=None):
    facts = git_facts(cwd)
    blockers = []

    if not Path(cwd).is_dir():
        # An unreachable directory fails the same git call as a real directory
        # outside any repo, so the causes have to be told apart here.
        blockers.append({
            "code": "cwd-unreadable",
            "detail": "{} does not exist or cannot be read.".format(cwd),
        })
    elif facts["repo_root"] is None:
        blockers.append({
            "code": "not-a-git-repo",
            "detail": "{} is not inside a git repository.".format(cwd),
        })
    elif not facts["status_ok"]:
        blockers.append({
            "code": "git-status-failed",
            "detail": "`git status` failed, so the tree state is unknown. "
                      "A clean-looking empty result cannot be trusted here.",
        })
    elif facts["unborn_branch"]:
        blockers.append({
            "code": "unborn-branch",
            "detail": "The repository has no commit yet, so there is no branch "
                      "to build on.",
        })
    elif facts["detached_head"]:
        blockers.append({
            "code": "detached-head",
            "detail": "HEAD is detached. Committing here orphans the work, and "
                      "the literal branch name \"HEAD\" reads as an ordinary "
                      "feature branch.",
        })
    elif not facts["tree_clean"]:
        blockers.append({
            "code": "dirty-tree",
            "detail": "Uncommitted or untracked changes: {}.".format(
                ", ".join(facts["dirty_paths"][:10])
            ),
        })

    doc = Path(handoff_doc)
    doc_readable = doc.is_file() and os.access(str(doc), os.R_OK)
    if not doc_readable:
        blockers.append({
            "code": "handoff-doc-unreadable",
            "detail": "Cannot read handoff document at {}.".format(handoff_doc),
        })

    auth_state = gh_auth_state(cwd)
    authenticated = auth_state == "ok"
    if auth_state == "timeout":
        blockers.append({
            "code": "gh-timeout",
            "detail": "`gh auth status` did not respond within {} seconds; "
                      "the network or proxy is not answering.".format(
                          GH_TIMEOUT_SECONDS
                      ),
        })
    elif not authenticated:
        blockers.append({
            "code": "gh-unauthenticated",
            "detail": "`gh` is unavailable or not authenticated; "
                      "the run could not open or update a PR.",
        })

    open_prs = gh_open_prs(cwd) if authenticated else None
    if authenticated and open_prs is not None and len(open_prs) >= PR_LIST_LIMIT:
        blockers.append({
            "code": "pr-lookup-truncated",
            "detail": "The open-PR listing filled its {}-entry window, so an "
                      "existing run PR cannot be ruled out.".format(PR_LIST_LIMIT),
        })
    if authenticated and open_prs is None:
        blockers.append({
            "code": "pr-lookup-failed",
            "detail": "`gh` is authenticated but could not list open pull "
                      "requests, so an existing run PR cannot be ruled out. "
                      "Proceeding would risk opening a duplicate.",
        })
    existing_pr = find_run_pr(open_prs, handoff_doc) if open_prs else None

    owners = (
        codeowners_for(facts["repo_root"], paths)
        if facts["repo_root"] and paths
        else {"file": None, "owners": [], "readable": True}
    )

    result = dict(facts)
    result.update({
        "handoff_doc": {"path": str(handoff_doc), "readable": doc_readable},
        "gh_auth_state": auth_state,
        "existing_pr": existing_pr,
        "codeowners": owners,
        "blockers": blockers,
    })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Mechanical preconditions for a /pickup run."
    )
    parser.add_argument("--handoff-doc", required=True)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--paths", nargs="*", default=[])
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_signal:
        # argparse exits 0 for --help and 2 for a bad argument. Preserve that
        # distinction: --help is a successful request, not a usage error.
        return USAGE_ERROR if exit_signal.code else CLEAR

    result = collect(args.cwd, args.handoff_doc, args.paths)
    print(json.dumps(result, indent=2, sort_keys=True))
    return BLOCKED if result["blockers"] else CLEAR


if __name__ == "__main__":
    sys.exit(main())
