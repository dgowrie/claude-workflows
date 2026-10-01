# Git Worktree Gotchas (Claude Code sessions)

Behaviors seen in sessions rooted in a git worktree (`.claude/worktrees/<name>/`). These look like stale caches, git errors, or flaky tools but are worktree isolation.

## File tools need the full worktree-prefixed absolute path

Read/Write/Edit resolve absolute paths literally. A main-checkout path like `/…/<repo>/src/foo.ts` silently reads/writes the MAIN checkout, not the worktree, even though Bash (running in the worktree cwd) sees the correct files.

- Symptom: Read shows old/main content while `grep`/`nl` via Bash show branch content; or a Write "succeeds" but never appears in the worktree.
- Apply: always prefix with the worktree root, e.g. `/…/<repo>/.claude/worktrees/<name>/src/foo.ts`. A stray write to the main checkout also trips the sandbox (`Operation not permitted`) and needs `dangerouslyDisableSandbox`.

## The session is hard-isolated to its worktree

- Cannot fast-forward local `main` (it's checked out in the shared checkout): `git fetch . origin/main:main` fails ("refusing to fetch into branch 'main' checked out at ..."), `git -C <main-checkout> ...` is refused by the harness ("must target its own worktree"), and even a user `!`-prefixed command is blocked. Do the `main` fast-forward from a shell OUTSIDE the worktree.
- `git -C <path>` is refused only when `<path>` is **another checkout of this worktree's own repo** (the shared main checkout, or a sibling worktree): "must target its own worktree". It is NOT blanket-refused by target: `git -C` against a **genuinely separate repo** (a different `.git`) works normally - full fetch / `worktree add` / commit / push / PR cycles all run fine there (verified 2026-09).
- Compound Bash commands are refused when the harness can't prove they stay in-worktree ("too complex to verify") - e.g. `cp …; …; >$TMPDIR/x.log` or `for i in $(seq …)` loops with redirects. Split into plain single-purpose commands, and prefer writing logs under the scratchpad absolute path over `$TMPDIR` redirects.

## `gh pr merge` half-succeeds from inside a worktree

`gh pr merge <n> --squash --delete-branch` exits with a bare `failed to run git: fatal: 'main' is already used by worktree at <main-checkout>` and no success output, which reads as "the merge did not happen". It did. gh merges server-side FIRST, then tries to check out local `main` to sync and delete the branch; only that second half hits the isolation guard.

- Symptom: a git error mentioning `main` is already used by worktree, immediately after invoking a merge. No PR URL, no "Merged" line.
- Apply: verify before retrying, `gh pr view <n> --json state,mergeCommit`. If `MERGED`, do NOT re-run the merge. Finish the cleanup by hand: `git push origin --delete <branch>` for the remote branch, and fast-forward `main` from outside the worktree (see above). The merged branch is still checked out in the worktree, so it cannot be deleted from there either; rename or leave it.
- Same shape applies to any `gh`/tool step that does a server action then a local checkout.

Why: these look like git errors or flaky tool failures but are the worktree-isolation guard.
