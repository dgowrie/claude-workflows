# config/scripts

Tooling that keeps committed Claude Code hooks from silently going inert, without
publishing personal settings to this public repo.

## Why this exists (issue #24)

Hook scripts, rules, skills, and agents in this repo are symlinked into `~/.claude/`,
so edits are immediately live. `~/.claude/settings.json` is the exception. It holds
the *hook wiring* (the `PreToolUse` matchers that decide whether a committed hook
actually fires) alongside personal posture prefs (`model`, `theme`, `sandbox`,
`skipDangerousModePermissionPrompt`, `skipAutoPermissionPrompt`, ...). Two facts
make it awkward to track:

- The posture prefs are personal and this is a **public** repo, so the live file
  can't just be committed or symlinked to a tracked copy.
- At user-global scope there is a single `settings.json` and **no** private
  overlay: a user-level `~/.claude/settings.local.json` is **not** honored for
  these keys (verified). So public and private keys can't be split across two
  user-scope files either.

So instead of tracking the live file, we track a **template** and validate the
live file's wiring:

1. `config/settings.example.json` is the tracked, reviewable template. It holds
   only shareable keys: the hook wiring plus the no-attribution policy
   (`includeCoAuthoredBy`, `attribution`). It carries **no** posture keys.
2. You copy it once to the untracked `~/.claude/settings.json` and add your
   private posture keys there.
3. `validate-hook-wiring.sh` asserts every committed hook is actually wired, run
   against both the template (is the checked-in wiring complete?) and your live
   file (is your real config still wiring every hook?).

## Scripts

- `install-settings.sh`: `--init` copies the template to `~/.claude/settings.json`
  (only if absent); `--check` (default) verifies the live file wires every hook.
- `validate-hook-wiring.sh`: fail if any `config/hooks/*.sh` is unwired or wired
  with an empty matcher in a given settings file.

Each has a companion `*.test.sh` (plain bash, no framework). Run them directly:

```bash
bash config/scripts/validate-hook-wiring.test.sh
bash config/scripts/install-settings.test.sh
```

> The test suites write fixtures under `mktemp -d`. Run them outside a restrictive
> sandbox (e.g. Claude Code's `auto-allow` sandbox blocks writes to the system
> temp dir), or they fail with "Operation not permitted".

### install-settings.sh

```bash
# First-time setup: copy the template into ~/.claude (only if it does not exist)
bash config/scripts/install-settings.sh --init

# Verify the live settings still wire every committed hook (default; read-only)
bash config/scripts/install-settings.sh --check
```

`--init` never overwrites an existing `~/.claude/settings.json` (it holds your
private posture keys). After `--init`, add your posture keys by hand:

```jsonc
{
  // ...copied from settings.example.json (hooks, attribution)...
  "model": "<your-model-id>",
  "theme": "dark",
  "sandbox": { "enabled": true, "mode": "auto-allow" },
  "skipDangerousModePermissionPrompt": true,
  "skipAutoPermissionPrompt": true
}
```

These posture keys are intentionally **not** tracked. Keep them only in the live
file.

`--check` errors if the live file is missing (`NOT INSTALLED`) or invalid JSON,
fails if any committed hook is unwired, and prints a non-fatal `note:` if the live
`hooks` block has drifted from the template (your matchers may legitimately
differ; the note just keeps the template honest).

Portable hook paths: `config/settings.example.json` uses `$HOME/.claude/hooks/...`
rather than an absolute `/Users/<you>/...` path. Claude Code runs hook commands
through `sh -c`, which expands `$HOME`, so the same template works on any machine.

### validate-hook-wiring.sh

```bash
# Check the tracked template wires every committed hook (defaults shown)
bash config/scripts/validate-hook-wiring.sh
# Or check an arbitrary settings file / hooks dir:
bash config/scripts/validate-hook-wiring.sh ~/.claude/settings.json config/hooks
```

It checks **presence + a non-empty matcher** for each hook, not whether the matcher
covers the "right" tools. Inferring intended tools from a script is brittle, and
the tracked template already makes the intended matchers visible in review. A hook
counts as wired if any `PreToolUse` command references its filename, tolerant of
trailing args and shell prefixes (`sh -c '.../foo.sh'`, `bash .../foo.sh`). A
future job could add a per-hook `# required-matcher:` annotation for stricter
checks.

## Adding a new hook

1. Add `config/hooks/<name>.sh` and symlink it: `ln -s ~/dev/claude-workflows/config/hooks/<name>.sh ~/.claude/hooks/<name>.sh`
2. Wire it in `config/settings.example.json` under `hooks.PreToolUse` with a matcher, and in your live `~/.claude/settings.json`.
3. Run `bash config/scripts/validate-hook-wiring.sh`; it fails until the template wires the hook.
