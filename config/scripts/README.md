# config/scripts

Tooling that keeps the tracked Claude Code config in `config/` from drifting away
from what is actually live in `~/.claude/`.

## Why this exists (issue #24)

Hook scripts, rules, skills, and agents in this repo are symlinked into `~/.claude/`,
so edits are immediately live. `~/.claude/settings.json` was the exception: a regular,
untracked file. It holds the *hook wiring* (the `PreToolUse` matchers that decide
whether a committed hook actually fires) plus model/theme/sandbox prefs. Because it
was untracked, a committed hook could silently never run, and the settings could
drift from the repo with no record.

Two pieces close that gap:

1. `config/settings.json` is the tracked source of truth, symlinked to
   `~/.claude/settings.json` (approach A).
2. `validate-hook-wiring.sh` asserts every committed hook is actually wired
   (approach B), so the tracked settings cannot fall out of sync with the hooks.

## Scripts

- `install-settings.sh`: symlink `~/.claude/settings.json` to `config/settings.json`; `--check` reports drift.
- `validate-hook-wiring.sh`: fail if any `config/hooks/*.sh` is unwired or wired with an empty matcher.

Each has a companion `*.test.sh` (plain bash, no framework). Run them directly:

```bash
bash config/scripts/validate-hook-wiring.test.sh
bash config/scripts/install-settings.test.sh
```

### install-settings.sh

```bash
# Link the tracked settings into ~/.claude (backs up any existing file first)
bash config/scripts/install-settings.sh

# Report link status + drift without changing anything (nonzero exit if drifted)
bash config/scripts/install-settings.sh --check
```

Portable hook paths: `config/settings.json` uses `$HOME/.claude/hooks/...` rather
than an absolute `/Users/<you>/...` path. Claude Code runs hook commands through
`sh -c`, which expands `$HOME`, so the same tracked file works on any machine.

#### Known caveat: `/config` may clobber the symlink

It is **not confirmed** whether Claude Code's own settings writer (`/config`, or
changing the theme in the TUI) writes *through* the symlink or *replaces* the file.
If it replaces it, `~/.claude/settings.json` silently becomes a regular file again
and the link to the repo is lost.

`install-settings.sh --check` detects exactly this: it flags "a regular file where a
symlink is expected" and preserves the current file as a `.backup.<timestamp>` when
you re-link, so no `/config` edits are lost. To confirm the behavior on your setup:
link the file, run `/config` to change the theme, then run `--check` and see whether
the symlink survived.

### validate-hook-wiring.sh

```bash
# Check the tracked settings wires every tracked hook (defaults shown)
bash config/scripts/validate-hook-wiring.sh
# Or check an arbitrary settings file / hooks dir:
bash config/scripts/validate-hook-wiring.sh ~/.claude/settings.json config/hooks
```

It checks **presence + a non-empty matcher** for each hook, not whether the matcher
covers the "right" tools. Inferring intended tools from a script is brittle, and
tracking `settings.json` already makes matcher edits visible in review. A future
job could add a per-hook `# required-matcher:` annotation for stricter checks.

## Adding a new hook

1. Add `config/hooks/<name>.sh` and symlink it: `ln -s ~/dev/claude-workflows/config/hooks/<name>.sh ~/.claude/hooks/<name>.sh`
2. Wire it in `config/settings.json` under `hooks.PreToolUse` with a matcher.
3. Run `bash config/scripts/validate-hook-wiring.sh`; it fails until the hook is wired.
