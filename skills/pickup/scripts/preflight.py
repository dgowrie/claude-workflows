#!/usr/bin/env python3
"""Report the mechanically checkable preconditions for a `/pickup` run.

Usage: preflight.py --handoff-doc <path> [--cwd <dir>] [--paths <path>...]

Prints one JSON object of facts on stdout and exits:

    0  clear    no mechanical blocker; the run may proceed to triage
    1  blocked  at least one blocker; `blockers` says which
    2  usage    the arguments were wrong; no facts were gathered
    3  crashed  the script itself failed; `blockers` holds one
                `preflight-crashed` entry and no other facts are reported

`--help` is the one exit 0 that prints usage text rather than JSON.

The point of this script is that `/pickup` runs unattended. A gate that depends
on the model remembering to check is not a gate, so every precondition that can
be settled by looking rather than by reasoning is settled here, once, and
reported as a fact.

The converse bound matters just as much: only mechanically determinable blockers
belong in `blockers`. Whether a handoff document contradicts its linked issue, or
whether a change is irreversible, is model judgment and lives in TRIAGE.md. This
script must never look like it has ruled on those.

Known bounds:

* CODEOWNERS matching follows the gitignore rules GitHub documents: anchoring
  by a leading or inner `/`, directory-only patterns, `*` within one segment,
  `**` across segments, and owner-less rules clearing ownership, with
  last-match-wins. Negation and `[ ]` ranges are treated as GitHub treats
  them, as not working. Under last-match-wins a missed match is not neutral,
  since it hands the path to an earlier rule, which is why the matcher has to
  be faithful rather than conservative. An unreadable CODEOWNERS reports
  `readable: false` rather than an empty owner list.
* The default branch is read from `origin/HEAD`, then from an `origin/main` or
  `origin/master` ref, then from a local `main` or `master`. Only a repo with no
  remote falls back to its current branch; a repo with a remote that resolves
  none of these reports `default-branch-unknown` rather than a guess.
* Resume detection looks for the exact citation line `/pickup` writes, naming
  the handoff document's basename, in the viewer's own open PR bodies. Two of
  the viewer's handoff documents sharing a basename would collide; the
  lowest-numbered match wins, so the collision resolves to a stable answer
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
from urllib.parse import urlparse

CLEAR, BLOCKED, USAGE_ERROR, CRASHED = 0, 1, 2, 3

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

DEFAULT_GH_HOST = "github.com"

# `ssh -G` only reads config, but config can run commands (`Match exec`).
SSH_TIMEOUT_SECONDS = 5

# The line `/pickup` writes into a PR body, and the only form resume accepts.
# A bare substring test let `old-handoff.md` claim a run cited as `handoff.md`.
RUN_CITATION = "Picked up from `{}`"

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


ORIGIN_PREFIX = "refs/remotes/origin/"
BRANCH_PREFIX = "refs/heads/"


def _probe(check, path):
    """`check(path)`, or None when the path cannot be examined at all.

    `Path.is_file` and `is_dir` raise on EACCES rather than returning False.
    Uncaught, that exits 1 with empty stdout, which is the blocked exit with
    nothing to read.
    """
    try:
        return check(path)
    except OSError:
        return None


def _current_branch(cwd):
    """The checked-out branch name, or None when HEAD is detached.

    Read from the full ref rather than `rev-parse --abbrev-ref HEAD`, which
    prints `heads/main` when a tag is also called `main`: that no longer
    equals the default branch, so a run on main would read as on a feature
    branch and keep committing to it. An unborn branch still has a name here.
    """
    code, out = run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd)
    ref = out.strip()
    if code == 0 and ref.startswith(BRANCH_PREFIX):
        return ref[len(BRANCH_PREFIX):]
    return None


def _default_branch(cwd, current_branch, unborn):
    """The default branch, or None when it cannot be established.

    Resolution runs from most to least authoritative: `origin/HEAD`, then an
    `origin/main` or `origin/master` ref, then a local `main` or `master`. Only
    a repo with no remote at all falls back to the current branch. With a
    remote configured that fallback is a guess that reads as a fact: on a
    feature branch it reports the feature branch as the default.
    """
    code, out = run(["git", "symbolic-ref", "--quiet", ORIGIN_PREFIX + "HEAD"], cwd)
    ref = out.strip()
    if code == 0 and ref.startswith(ORIGIN_PREFIX):
        # Strip the prefix rather than splitting on "/": a default branch may
        # itself contain one, as in `release/x`.
        return ref[len(ORIGIN_PREFIX):]
    for ref_prefix in (ORIGIN_PREFIX, "refs/heads/"):
        for candidate in ("main", "master"):
            code, _ = run(
                ["git", "show-ref", "--verify", "--quiet", ref_prefix + candidate],
                cwd,
            )
            if code == 0:
                return candidate
    code, remotes = run(["git", "remote"], cwd)
    if code != 0 or remotes.strip():
        return None
    # An unborn branch has a name but nothing on it, so it is no base to branch
    # from; reporting it as the default would make it trivially "on" default.
    return None if unborn else current_branch


def _dirty_paths(porcelain):
    """Paths from `git status --porcelain -z`, including untracked.

    Untracked files count as dirty. An unattended run must not bulldoze work
    whose origin it cannot establish, and untracked files are precisely the case
    where it has the least idea what it would be destroying.

    Split on NUL rather than `str.splitlines`, which also breaks on U+0085 and
    other characters git allows in a name. A name split that way leaves
    fragments too short to keep, and the tree reads as clean.
    """
    paths = []
    entries = iter(porcelain.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        # A rename or copy is followed by a second field naming its origin; the
        # destination, in this entry, is what exists now.
        if entry[0] in "RC":
            next(entries, None)
        paths.append(entry[3:])
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

    branch = _current_branch(cwd)
    # A failed `git status` prints nothing, which is indistinguishable from a
    # clean tree. Keeping the return code is what stops the dirty-tree gate
    # from failing open on an unknown tree state. The explicit flags override
    # config that would hide untracked files or modified submodules, which
    # empties the output the same way; `normal` rather than `all` because
    # listing every file inside an untracked directory can be slow, and this
    # call deliberately has no deadline.
    status_code, porcelain = run(
        [
            "git", "status", "--porcelain", "-z",
            "--untracked-files=normal", "--ignore-submodules=none",
        ],
        cwd,
    )
    status_ok = status_code == 0
    dirty = _dirty_paths(porcelain)

    # `symbolic-ref` fails only when HEAD is detached, leaving no branch name;
    # `rev-parse --verify HEAD` fails only before the first commit.
    verify_code, _ = run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd)
    unborn = verify_code != 0
    detached = branch is None and not unborn
    default = _default_branch(cwd, branch, unborn)

    return {
        "repo_root": root,
        "current_branch": branch,
        "default_branch": default,
        "on_default_branch": bool(default) and branch == default,
        "tree_clean": status_ok and not dirty,
        "status_ok": status_ok,
        "detached_head": detached,
        "unborn_branch": unborn,
        "dirty_paths": dirty,
    }


def _segments_match(pattern_parts, path_parts):
    """Glob segment by segment, with `**` standing for zero or more segments.

    Matching segment by segment confines `*` to one segment, where `fnmatch`
    on a whole path would let it span separators. `fnmatchcase` because
    CODEOWNERS paths are case sensitive even on a case-insensitive host.
    """
    if not pattern_parts:
        return not path_parts
    head, rest = pattern_parts[0], pattern_parts[1:]
    if head == "**":
        return any(
            _segments_match(rest, path_parts[skip:])
            for skip in range(len(path_parts) + 1)
        )
    return (
        bool(path_parts)
        and fnmatch.fnmatchcase(path_parts[0], head)
        and _segments_match(rest, path_parts[1:])
    )


def _codeowners_matches(pattern, path):
    """Whether a CODEOWNERS pattern claims `path`, by gitignore rules.

    A pattern anchors to the root when it starts with `/` or has a `/` before
    its end; otherwise it matches at any depth. A trailing `/` restricts it to
    directories. Matching a directory claims everything beneath it, so every
    ancestor of `path` is a candidate as well as `path` itself.

    Except after a final bare `*`: GitHub documents that `docs/*` matches
    `docs/getting-started.md` but not `docs/build-app/troubleshooting.md`, so
    there only `path` itself is a candidate. Plain gitignore differs here, and
    GitHub is what decides who reviews.

    `[` is literal: GitHub documents that character ranges do not work, and
    letting `fnmatch` treat one as a range would claim paths GitHub does not.
    """
    directory_only = pattern.endswith("/")
    body = pattern.strip("/")
    if not body:
        return False
    anchored = pattern.startswith("/") or "/" in body
    pattern_parts = body.replace("[", "[[]").split("/")
    if not anchored:
        pattern_parts = ["**"] + pattern_parts
    path_parts = path.strip("/").split("/")
    if pattern_parts[-1] == "*" and not directory_only:
        return _segments_match(pattern_parts, path_parts)
    last = len(path_parts) - 1 if directory_only else len(path_parts)
    return any(
        _segments_match(pattern_parts, path_parts[:depth])
        for depth in range(1, last + 1)
    )


def codeowners_for(repo_root, paths):
    """Owners of `paths`, unioned, using last-match-wins per path.

    `readable` separates "no rule matched" from "the file could not be read".
    Collapsing the two into an empty owner list is a silent zero: the run would
    report that nobody owns the code when it had simply failed to look.
    """
    root = Path(repo_root)
    location = None
    for candidate in CODEOWNERS_LOCATIONS:
        present = _probe(Path.is_file, root / candidate)
        if present is None:
            # Whether a file exists here is unknown, so a later location
            # cannot be trusted to be the one GitHub would use.
            return {"file": None, "owners": [], "readable": False}
        if present:
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
        # Negation does not work in CODEOWNERS, so a `!` rule matches nothing.
        if fields[0].startswith("!"):
            continue
        # A rule with no owners is kept: it clears ownership for what it
        # matches, so skipping it would hand those paths to an earlier rule.
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


def _ssh_hostname(host, cwd):
    """The real host behind an SSH alias, as gh resolves it.

    Mirrors go-gh's translator: the last `hostname` line of `ssh -G <host>`,
    the original host on any failure, and `ssh.github.com` (GitHub's port-443
    endpoint) mapped back to github.com.
    """
    code, out = run(["ssh", "-G", host], cwd, timeout=SSH_TIMEOUT_SECONDS)
    resolved = host
    if code == 0:
        for line in out.splitlines():
            key, _, value = line.partition(" ")
            if key == "hostname" and value.strip():
                resolved = value.strip()
    if resolved.lower() == "ssh.github.com":
        return DEFAULT_GH_HOST
    return resolved


def _github_host(cwd):
    """The host `gh` will talk to for this repo.

    `GH_HOST` wins, as it does for `gh` itself, which then ignores remotes on
    other hosts. Otherwise the `origin` URL's host, through the same SSH alias
    translation gh applies to `ssh://` and scp-like `user@host:path` remotes;
    otherwise github.com. Reading an alias verbatim reports a working login as
    unauthenticated and blocks every run.
    """
    if os.environ.get("GH_HOST"):
        return os.environ["GH_HOST"]
    code, url = run(["git", "remote", "get-url", "origin"], cwd)
    url = url.strip()
    if code != 0 or not url:
        return DEFAULT_GH_HOST
    if "://" in url:
        parsed = urlparse(url)
        if not parsed.hostname:
            return DEFAULT_GH_HOST
        if parsed.scheme == "ssh":
            return _ssh_hostname(parsed.hostname, cwd)
        return parsed.hostname
    if ":" in url:
        host = url.split(":", 1)[0].rsplit("@", 1)[-1]
        return _ssh_hostname(host, cwd) if host else DEFAULT_GH_HOST
    return DEFAULT_GH_HOST


def gh_auth_state(cwd):
    """One of "ok", "timeout", or "unauthenticated".

    A hung network call and a missing credential need different remedies, so
    reporting both as unauthenticated sends the reader after the wrong problem.

    Scoped to the active account on the repo's host. Unscoped, `gh auth status`
    exits 1 when any account on any host has a problem, so one stale login
    elsewhere would block every run. A `gh` too old to know `--active` exits 1
    here too, which blocks rather than proceeds.
    """
    code, _ = run(
        ["gh", "auth", "status", "--hostname", _github_host(cwd), "--active"],
        cwd,
        timeout=GH_TIMEOUT_SECONDS,
    )
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
            "--json", "number,url,headRefName,body,author,isCrossRepository",
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


def gh_viewer(cwd):
    """The authenticated login on the repo's host, or None when unknown."""
    code, out = run(
        ["gh", "api", "user", "--hostname", _github_host(cwd), "--jq", ".login"],
        cwd,
        timeout=GH_TIMEOUT_SECONDS,
    )
    login = out.strip()
    return login if code == 0 and login else None


def find_run_pr(prs, handoff_doc, viewer):
    """The open PR belonging to this run, or None.

    Keyed on the handoff document a PR body cites rather than on the branch name,
    so a run resumes even when the branch was renamed between sessions. Only the
    viewer's own PRs qualify: the mandate forbids touching anyone else's, and a
    colleague's PR citing the same filename is not this run.
    """
    citation = RUN_CITATION.format(os.path.basename(handoff_doc))
    matches = [
        pr for pr in prs
        if citation in (pr.get("body") or "")
        and (pr.get("author") or {}).get("login") == viewer
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda pr: pr.get("number", 0))[0]


def find_branch_pr(prs, branch):
    """The open same-repo PR whose head is `branch`, or None.

    Fork PRs are excluded: they routinely reuse names like `patch-1`, and the
    run never pushes to a fork.
    """
    for pr in sorted(prs, key=lambda pr: pr.get("number", 0)):
        if pr.get("headRefName") == branch and not pr.get("isCrossRepository"):
            return pr
    return None


def collect(cwd, handoff_doc, paths=None):
    facts = git_facts(cwd)
    blockers = []

    if not _probe(Path.is_dir, Path(cwd)):
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
            "detail": "HEAD is detached, so there is no branch to keep. "
                      "Committing here orphans the work.",
        })
    elif facts["default_branch"] is None:
        blockers.append({
            "code": "default-branch-unknown",
            "detail": "The default branch could not be established, so there "
                      "is no known base to branch from. `git remote set-head "
                      "origin --auto` usually fixes this.",
        })
    elif not facts["tree_clean"]:
        blockers.append({
            "code": "dirty-tree",
            "detail": "Uncommitted or untracked changes: {}.".format(
                ", ".join(facts["dirty_paths"][:10])
            ),
        })

    doc = Path(handoff_doc)
    doc_readable = bool(_probe(Path.is_file, doc)) and os.access(str(doc), os.R_OK)
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
    viewer = gh_viewer(cwd) if authenticated and open_prs is not None else None
    if authenticated and open_prs is not None and viewer is None:
        blockers.append({
            "code": "gh-viewer-unknown",
            "detail": "Could not read the authenticated login, so this run's "
                      "own PR cannot be told apart from anyone else's.",
        })
    existing_pr = (
        find_run_pr(open_prs, handoff_doc, viewer) if open_prs and viewer else None
    )
    branch = facts["current_branch"]
    current_branch_pr = (
        find_branch_pr(open_prs, branch)
        if open_prs and branch and not facts["on_default_branch"]
        and not facts["detached_head"]
        else None
    )
    if current_branch_pr and (
        not existing_pr or current_branch_pr["number"] != existing_pr["number"]
    ):
        blockers.append({
            "code": "branch-has-other-pr",
            "detail": "{} already carries PR #{}, which is not this run's. "
                      "Keeping the branch would push onto it.".format(
                          branch, current_branch_pr["number"]
                      ),
        })

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
        "current_branch_pr": current_branch_pr,
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

    try:
        result = collect(args.cwd, args.handoff_doc, args.paths)
    except Exception as error:  # noqa: BLE001
        # A traceback leaves the caller parsing an empty stdout. Keep the JSON
        # contract and give the failure its own exit code, so "blocked" never
        # has to mean "crashed".
        print(json.dumps({
            "blockers": [{
                "code": "preflight-crashed",
                "detail": "preflight.py raised {}: {}".format(
                    type(error).__name__, error
                ),
            }],
        }, indent=2, sort_keys=True))
        return CRASHED
    print(json.dumps(result, indent=2, sort_keys=True))
    return BLOCKED if result["blockers"] else CLEAR


if __name__ == "__main__":
    sys.exit(main())
