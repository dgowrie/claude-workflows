# Self-Correction Loop

On correction (user or self-caught): propose `CLAUDE.md` or rule file update **immediately, before continuing the task**.

- **Trigger**: user correction; or self-correction worth generalizing
- **Scope**: substantive mistakes, violated preferences, meaningful tone/style findings
- **Target**: global `~/.claude/CLAUDE.md` if broadly applicable; the most local `CLAUDE.md` otherwise. Discrete concerns get their own rule file in `~/.claude/rules/`.
- **Process**: (1) stop task (2) propose rule + reasoning (3) apply on confirmation (4) resume
