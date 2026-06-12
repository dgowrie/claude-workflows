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

## Adding a new skill

When adding a skill to `skills/`:

1. Create `skills/<name>/SKILL.md` with `user-invocable: true` in frontmatter
2. Symlink into `~/.claude/skills/`: `ln -s ~/dev/claude-workflows/skills/<name> ~/.claude/skills/<name>`
3. Add an entry to the Skills section in `README.md`

## Adding a new agent

When adding a subagent definition to `agents/`:

1. Create `agents/<name>.md` (frontmatter with `name`, `description`, `model`; optional `memory: user` for persistent agent memory)
2. Symlink into `~/.claude/agents/`: `ln -s ~/dev/claude-workflows/agents/<name>.md ~/.claude/agents/<name>.md`
3. Add an entry to the Agents section in `README.md`
