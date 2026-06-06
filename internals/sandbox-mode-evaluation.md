# Claude Code Sandbox Mode Evaluation

How sandbox mode works, what it restricts, and when to use it vs. Docker isolation.

---

## Enabling Sandbox Mode

### Via settings.json (persistent, schema can change)

Use `/sandbox` once, then inspect settings at both scopes:

- `~/.claude/settings.json` (global defaults)
- `<repo>/.claude/settings.json` (project overrides, when present)

This doc intentionally avoids pinning an unverified `sandbox.enabled`/`sandbox.mode` schema example.
Key names and structure can vary across Claude Code versions.

### Via `/sandbox` command (interactive, ad-hoc)

Opens a menu to choose between auto-allow and regular permissions. Can toggle mid-session.

### Platform requirements

- **macOS**: works out of the box (Seatbelt)
- **Linux/WSL2**: install `bubblewrap` and `socat`
- **WSL1**: not supported

---

## What the Sandbox Restricts

### Filesystem

- Writes confined to CWD and subdirectories by default
- Reads allowed broadly
- Extra write capability is typically granted through permission allowlist patterns (for example, `permissions.allow` entries) rather than `sandbox.filesystem.*` configuration keys

### Network

- Only approved domains are reachable by default
- New domains trigger prompts (or deny in stricter permission modes)
- Domain-level only, no TLS inspection

### Protected paths (different protection semantics)

- **Repo metadata/config paths (never auto-approved):** `.git`, `.claude`, `.vscode`, `.idea`, `.husky`
- **User-home config/credential paths (high-friction; typically prompt/deny):** `~/.gitconfig`, `~/.bashrc`, `~/.zshrc`, `~/.ssh`
- **System paths (outside normal write scope; prompt/deny):** `/bin`, `/usr`

### Enforcement

OS-level (Seatbelt on macOS, bubblewrap on Linux). All child processes inherit restrictions.

---

## Auto-Allow Mode Security Boundaries

### Auto-allows (no prompts)

- Bash commands within sandbox boundaries
- File writes/deletes inside CWD
- Network requests to pre-approved domains

### Still prompts

- Remote-modifying commands (`git push`, `gh pr create`, `gh api` POST/DELETE)
- Writes outside CWD (unless explicitly allowed)
- Network to unapproved domains

---

## Risk Assessment (repo-scoped session)

| Concern | Risk | Notes |
| --- | --- | --- |
| Deletes files in repo | Possible | Reversible via git |
| Modifies files outside repo | Blocked | Sandbox boundary |
| Pushes to remote | Prompts | Not auto-allowed |
| Creates/closes PRs or issues | Prompts | Not auto-allowed |
| Exfiltrates code | Mitigated | Unapproved domains are blocked, but approved domains can still be exfiltration paths |
| Modifies git/shell config | Blocked | Protected path |
| Malicious subprocess escapes | Blocked | OS-enforced |

---

## Native Sandbox vs Docker

| Feature | Native Sandbox | Docker Container |
| --- | --- | --- |
| Setup | Built-in, zero deps (macOS) | Docker daemon + image management |
| Performance | Near-native | Higher overhead, slower I/O |
| Filesystem | Selective read/write | All-or-nothing volume mounts |
| Network | Domain-level filtering | Complete isolation unless ports exposed |
| Dev workflow | IDE, shell, tools seamless | Must enter container; separate tooling |
| Isolation strength | OS sandbox primitives | Full kernel-level isolation (stronger) |
| Escape difficulty | `dangerouslyDisableSandbox` flag (prompts user) | Harder (unless `--privileged`) |

### When native sandbox fits

- Local dev with trusted code
- CI/CD (fewer dependencies)
- Performance-sensitive workflows
- Autonomous Claude with guardrails, not container friction

### When Docker fits better

- Untrusted third-party code
- Strict compliance requiring full OS isolation
- Multi-tenant scenarios
- Complete network lockdown needed

The two approaches are complementary. Some teams run Claude Code with native sandboxing inside a Docker container for defense in depth.
