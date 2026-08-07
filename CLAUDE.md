# CLAUDE.md — claude-workflows

This repo contains reference material, learnings, and tools for working with Claude Code. Content should be concise, practical, and grounded in real usage — not theoretical.

## Content guidelines

- Write for an audience of practitioners who already use Claude Code
- Favor concrete examples over abstract explanations
- When documenting a finding, include what was observed and why it matters — skip obvious implications
- Keep markdown files scannable: tables, short bullets, clear headings
- Presentations (Reveal.js HTML) should accompany their source markdown, not replace it

## Directory structure

- `internals/` — how Claude Code works under the hood (directories, memory, plans, etc.)
- `workflows/` — patterns and practices for working effectively with Claude Code
- `explorations/` — session notes and findings from investigating Claude Code behavior
- `skills/` — skill drafts and development (before deploying to `~/.claude/skills/`)
- `config/` — global `CLAUDE.md` and `rules/`, symlinked into `~/.claude/`

## Adding a new rule

When adding a rule to `config/rules/`:

1. Create `config/rules/<name>.md` (plain markdown, optional `paths` frontmatter for scoping)
2. Symlink into `~/.claude/rules/`: `ln -s ~/dev/claude-workflows/config/rules/<name>.md ~/.claude/rules/<name>.md`
3. Add an entry to the Rules section in `README.md`

**The repo is the single source of truth.** Author the rule in `config/rules/` and reach `~/.claude/rules/` only through the symlink. Never write a rule as a plain file directly in `~/.claude/rules/`; that leaves it live locally but untracked, so it never reaches the repo or peers. This applies even when a self-correction fires mid-task in another project: create the file under `config/rules/` in this repo, then symlink. If you find a plain (non-symlink) rule already sitting in `~/.claude/rules/`, migrate it: move the content into `config/rules/<name>.md`, replace the original with a symlink, and add the README entry (steps 1-3 above).

## Adding a new skill

When adding a skill to `skills/`:

1. Create `skills/<name>/SKILL.md` with `name` and `description` in frontmatter
2. Decide invocation (see below) and set `disable-model-invocation` accordingly
3. Symlink into `~/.claude/skills/`: `ln -s ~/dev/claude-workflows/skills/<name> ~/.claude/skills/<name>`
4. Add an entry to the Skills section in `README.md`

### Choosing invocation

`disable-model-invocation` is the field that matters. `user-invocable` defaults to `true` and only controls `/` menu visibility, so writing `user-invocable: true` is a no-op; set `user-invocable: false` only to hide a skill from the menu while leaving Claude able to load it.

| Frontmatter | You can `/invoke` | Claude can auto-fire | Context cost |
| --- | --- | --- | --- |
| `description` only (default) | Yes | Yes | Description always loaded |
| `disable-model-invocation: true` | Yes | No | Removed from Claude's context entirely |
| `user-invocable: false` | No | Yes | Description always loaded |

Default to leaving model invocation on. Set `disable-model-invocation: true` when the skill has side effects you want to time yourself, or when it is expensive and should never fire uninvited. Keep it off when Claude should reach the skill on its own, when another skill invokes it by name, or when it should preload into subagents; a model-invoked skill is still `/`-invocable, so a description only ever adds reach.

Write the `description` for whichever audience can see it: model-facing with trigger branches when Claude can fire it, a plain human-facing one-liner when it cannot.

## Adding a new agent

When adding a subagent definition to `agents/`:

1. Create `agents/<name>.md` (frontmatter with `name`, `description`, `model`; optional `memory: user` for persistent agent memory)
2. Symlink into `~/.claude/agents/`: `ln -s ~/dev/claude-workflows/agents/<name>.md ~/.claude/agents/<name>.md`
3. Add an entry to the Agents section in `README.md`
