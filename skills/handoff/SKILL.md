---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS - not the current workspace.

Include a "suggested skills" section in the document, which suggests skills that the agent should invoke.

Do not duplicate content already captured in other artifacts (PRDs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.

Do NOT spawn a subagent or otherwise continue the handed-off work in the current session. A subagent runs inside this session and draws on its context budget, which defeats the purpose of a handoff. Your job ends at producing the document.

After writing the document, print its absolute path and instruct the user to start a fresh session themselves: run `/clear`, then `read <path>`. This step is the user's to perform - the model cannot invoke `/clear` (it is a harness command, not a skill), and clearing wipes the conversation, so no in-session automation can carry the work across the boundary.
