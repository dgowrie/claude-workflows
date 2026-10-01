# Temp-File Path Discipline (for `--body-file`, `-F`, `@file`, config inputs)

Context: I once created a PR whose body was stale content from an unrelated task. Cause: I wrote the body with the Write tool to the scratchpad path, but the `gh pr create` command read `$TMPDIR/pr_body.md`, a different location that happened to hold a leftover file from a prior task. `gh` silently used the stale file (it existed, so no error), and an outward-facing PR shipped with wrong content and wrong issue links.

Rules to never repeat it:

1. **Write and read the exact same absolute path.** When a command consumes a file (`gh ... --body-file`, `curl -d @file`, `-F`, config paths), the path I Write to and the path I pass to the command must be byte-identical. Do not Write to path A and read `$VAR/...` hoping they match.

2. **Do not assume `$TMPDIR` equals the session scratchpad.** They are often different directories. If I want the scratchpad, use the full scratchpad absolute path, not `$TMPDIR/...`.

3. **Use unique, task-specific filenames.** Never reuse a generic name like `pr_body.md` in a shared temp dir; a prior task may have left one there. Include the task/feature and a version suffix (e.g. `ap_ga_pr_body_v2.md`).

4. **Verify outward-facing artifacts after creation.** After creating/editing a PR, issue, or comment from a file, read it back (`gh pr view --json body`) and confirm the content is what I intended before reporting done. This applies to anything published to an external service.

Prefer passing body text inline when the tool allows it, to avoid the file indirection entirely.
