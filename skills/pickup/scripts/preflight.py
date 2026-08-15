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

CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def run(args, cwd):
    """Run a command, returning (returncode, raw stdout). Never raises.

    Deliberately unstripped. `git status --porcelain` encodes the status in the
    first two columns, so leading whitespace is data; stripping it here silently
    shifted every reported path by one character. Callers wanting a scalar strip
    at the call site.
    """
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError):
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
    _, current = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return current.strip() or None


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
    return {
        "repo_root": root,
        "current_branch": branch or None,
        "default_branch": default,
        "on_default_branch": bool(branch) and branch == default,
        "tree_clean": status_ok and not dirty,
        "status_ok": status_ok,
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
    cleaned = pattern.lstrip("/")
    if cleaned.endswith("/"):
        return path.startswith(cleaned)
    if "/" not in cleaned:
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
        contents = (root / location).read_text()
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


def gh_authenticated(cwd):
    code, _ = run(["gh", "auth", "status"], cwd)
    return code == 0


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
            "--limit", "100",
        ],
        cwd,
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

    authenticated = gh_authenticated(cwd)
    if not authenticated:
        blockers.append({
            "code": "gh-unauthenticated",
            "detail": "`gh` is unavailable or not authenticated; "
                      "the run could not open or update a PR.",
        })

    open_prs = gh_open_prs(cwd) if authenticated else None
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
        "gh_authenticated": authenticated,
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
