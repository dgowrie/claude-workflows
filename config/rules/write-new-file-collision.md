# Write: Verify a Path Is New Before Creating

Using the Write tool to "create" a file at a path that already holds content silently overwrites it. This once clobbered an existing test file that was assumed not to exist. Root causes: (1) Write was treated as create-new without confirming the path was empty; (2) an earlier grep for terms the file did not contain missed it, and that absence was read as "no such file".

## Rules

1. **Confirm the path is new before Write-creating.** Before Write on a path you intend as NEW (as opposed to deliberately overwriting a file you Read this session), verify nothing exists there: `ls <path>` / `test -f`, `git status`, or a directory listing you already have. Especially for conventionally-named files (`*.test.ts`, `index.tsx`, `handlers.ts`, `utils.ts`, `constants.ts`) where a name collision is likely.

2. **A missing search hit is not evidence of absence.** A file can exist and not match your grep terms (e.g. a handler test that exercises the code via `fetch` and names neither the function nor the module). Check the path itself, not a content search, before concluding a file is absent. (See the "treating absence as evidence" failure mode in epistemic-honesty.)

3. **If it exists, Read then Edit/append.** Never let Write silently replace existing content. Fold new content into the existing file (Edit) rather than overwriting it.

4. **After an accidental clobber:** `git checkout <path>` to restore, then re-apply the intended change as an Edit/append onto the restored content.
