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

## Adding a new skill

When adding a skill to `skills/`:

1. Create `skills/<name>/SKILL.md` with `user-invocable: true` in frontmatter
2. Symlink into `~/.claude/skills/`: `ln -s ~/dev/claude-workflows/skills/<name> ~/.claude/skills/<name>`
3. Add an entry to the Skills section in `README.md`
