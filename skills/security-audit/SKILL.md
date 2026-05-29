---
name: security-audit
user-invocable: true
description: >
  Source-code-level security audit that scans for vulnerabilities automated dependency scanners
  can't find: XSS, injection, SSRF, secret leakage, unsafe deserialization, open redirects,
  prototype pollution, and more. Runs a three-phase workflow: dependency scan, parallelized
  source code audit (batched by functional area), and verification pass with false-positive
  triage. Outputs findings to a GitHub tracking issue with linked sub-issues for each verified
  action item. Use this skill when asked to run a security audit, find CVEs in source code,
  check for vulnerabilities, or do a security review of the codebase. Trigger phrases: "security
  audit", "find CVEs", "vulnerability scan", "source code audit", "check for vulnerabilities",
  "security scan".
---

# Security Audit

You are conducting a systematic source-code-level security audit. Your job is to find
vulnerabilities that automated dependency scanners (Trivy, Grype, Dependabot, Renovate, OSV
Scanner) cannot detect. Focus on code-level issues reachable by users or triggered via crafted
input.

---

## Phase 0: Orient

Before anything else, understand the project:

1. **Identify the stack**: language, framework, package manager, project type (frontend plugin,
   backend API, CLI tool, library, etc.)
2. **Count source files**: exclude tests, config, mocks, generated code. Get a line count.
3. **Identify the deployment context**: where does this run, what auth layer sits in front, what
   does the app have access to (database, filesystem, network, secrets)?
4. **Check existing security tooling**: CI workflows, dependency scanners, audit scripts, Renovate
   config. Understand what's already covered.
5. **Present the deployment context and scope to the user** for confirmation before proceeding.

This orientation shapes everything: threat model, batch strategy, and what counts as exploitable.

---

## Phase A: Dependency Scan (quick win)

Run the appropriate audit command for the detected package manager (e.g., `npm audit`,
`yarn audit` for Yarn Classic v1, `yarn npm audit` for Yarn Berry v2+, `go vuln check`, etc.):

- Filter results by severity
- Cross-reference with existing resolutions/pins
- Note which vulnerabilities are in devDependency chains (not shipped)
- Note which are already covered by external scanners

**Create a GitHub tracking issue** with the audit title, scope description, deployment context,
and Phase A results. All subsequent phases append to this issue.

If no package manager audit is available, skip to Phase B and note the gap.

---

## Phase B: Source Code Audit (parallelized)

### Batch strategy

Group source files into **8-12 functional batches** by area of concern, not one agent per file.
Batch boundaries should follow data flow (e.g., API layer, hooks/state, UI components that render
user data, utility functions). Aim for ~500-1500 lines per batch.

For each batch, spawn a subagent with:
- The specific files to audit
- The deployment context from Phase 0
- The vulnerability checklist (adapted to the stack - see below)
- The finding report format

### Vulnerability checklist (adapt per stack)

**Frontend (React/TypeScript/JavaScript)**:
- XSS: `dangerouslySetInnerHTML`, `innerHTML`, `__html`, `document.write`, `insertAdjacentHTML`,
  string-to-DOM without sanitization
- Injection: user input interpolated into URLs, queries, or commands without encoding/validation
- SSRF: user-controlled input influencing fetch URLs or proxy destinations
- Open redirects: redirect URLs from query params or location state
- Prototype pollution: deep merge/spread on untrusted objects, `__proto__` in JSON
- Secret leakage: tokens/keys in source, sensitive data in telemetry/error messages/localStorage
- Unsafe deserialization: `eval()`, `new Function()`, `JSON.parse` of untrusted input used unsafely
- ReDoS: regex patterns with catastrophic backtracking potential on user input
- Missing auth checks: UI exposing controls without checking permissions

**Backend (Go/Python/Java/etc.)**:
- All of the above, plus:
- SQL injection, NoSQL injection, LDAP injection
- Path traversal in file operations
- Command injection via `exec`/`system`/`subprocess`
- Race conditions (TOCTOU, concurrent map access)
- Insecure cryptography (weak algorithms, hardcoded keys, predictable randomness)
- Missing rate limiting on sensitive endpoints
- Tenant isolation flaws (shared caches, missing tenant scoping on queries)

### Subagent prompt template

Each subagent gets this structure (fill in the blanks per batch):

```
You are conducting a security audit of a {project_type} ({stack}).
Your batch: {batch_description}.

**Deployment context**: {deployment_context}

**Your files to audit** (read all of them):
{file_list}

**What to look for**:
{relevant_checklist_items}

**For each finding**, report in this exact format:

### FINDING-{BATCH_ID}-{N}: {one-line summary}
**Severity**: Critical / High / Medium / Low / Informational
**File**: {file}:{line}
**Reachability**: How an attacker reaches this code path
**Root cause**: What's wrong and what check is missing
**Impact**: What an attacker gains
**Fix sketch**: Concrete code change

If nothing exploitable is reachable, say "No findings in this batch" with a brief
explanation of why the code is safe.

Do NOT pad findings. Only report genuinely exploitable issues or meaningful risks.
Informational findings are OK if they represent defense-in-depth gaps.
```

### After all batches complete

Append a Phase B summary to the tracking issue:
- List clean batches with brief rationale
- List all findings in a table (ID, summary, severity, status)
- Include an overall assessment

---

## Phase C: Verification Pass

Review all Phase B findings against the actual source code:

1. **Deduplicate**: merge findings that describe the same root cause from different batches
2. **Verify reachability**: confirm the attack path exists by tracing from user input to sink
3. **Triage false positives**: mark findings as false-positive with a specific reason
4. **Assign final severity**: adjust based on verified reachability and deployment context

### False-positive reasons (common patterns)

- Input comes from server response, not user input (defense-in-depth only)
- Framework auto-escapes at the sink (e.g., React JSX text interpolation)
- Auth layer prevents unauthorized access to the code path
- Value is validated/sanitized upstream before reaching the sink
- Feature is gated behind admin-only access (attacker = admin is out of scope)

### Create sub-issues

For each verified finding (not false-positive), create a GitHub issue and link it as a **native
sub-issue** of the tracking issue using GitHub's sub-issue API:

1. Create the issue: `gh issue create --title "{ID}: {one-line summary}" --label security --body "..."`
2. Get the node IDs for both the new issue and the parent tracking issue
3. Link as sub-issue via GraphQL:
   ```
   gh api graphql -f query='mutation {
     addSubIssue(input: {issueId: "<PARENT_NODE_ID>", subIssueId: "<CHILD_NODE_ID>"}) {
       issue { id }
       subIssue { id }
     }
   }'
   ```

The phase comments should still reference sub-issues in tables and lists as defined above, but
the native sub-issue relationship is **required in addition** - do not rely on comment references
alone. The parent issue's sub-issue summary must reflect all findings.

Each sub-issue body should include: summary, severity, reachability, root cause, impact, fix options.

Append Phase C results to the tracking issue: verification table, false-positive rationale, and
overall assessment.

---

## Output format

The tracking issue should have this structure when complete:

1. **Issue body**: scope, deployment context, Phase A dependency results
2. **Comment 1**: Phase B source audit results (clean batches, findings table, assessment)
3. **Comment 2**: Phase C verification (verified sub-issues table, false positives, final assessment)
4. **Sub-issues**: one per verified finding, linked via GitHub's native sub-issue relationship
   (not markdown checklists or comment references)

---

## Cost estimation

Before starting Phase B, estimate token cost based on:
- Number of source files and total lines
- Number of planned batches
- Model (Opus ~$15/1M input tokens, Sonnet ~$3/1M)

Present the estimate to the user. Typical ranges:
- Small repo (<10K lines): $10-25 on Opus
- Medium repo (10-50K lines): $25-75 on Opus
- Large repo (50K+ lines): consider Sonnet for batch agents with Opus for verification

---

## Graduation path: GitHub Actions workflow

> **Status**: planned - iterate on this skill first, then graduate the matured prompt.

Once the skill prompt is stable and producing consistent, high-quality results, it can be
extracted into a GitHub Actions workflow for scheduled or on-demand runs.

### Viable approaches

**Option A: `workflow_dispatch` + Claude Code CLI**
- Manually triggered GH Action that runs `claude` CLI with the audit prompt
- Pros: gets subagent parallelism, tool use, and file reading natively; `gh` CLI available for
  issue creation; closest to the interactive skill experience
- Cons: needs API key in GH secrets, token costs per run, CLI version pinning

**Option B: `workflow_dispatch` + Claude API direct**
- GH Action calls the Claude API with structured prompts for each phase
- Pros: more control over token usage, can batch/parallelize via API, no CLI dependency
- Cons: loses subagent orchestration (must implement in workflow logic), more prompt engineering
  for unattended mode, context window management for larger repos

**Option C: Scheduled + either approach**
- Cron-triggered (e.g., monthly) using either option above
- Pros: continuous coverage, drift detection
- Cons: cost accumulates, needs dedup logic against prior runs' issues

### Recommendation

Start with **Option A** (`workflow_dispatch` + Claude Code CLI). It's the most direct port of
this skill. Add scheduling (Option C) once the on-demand version is validated.

Key considerations for the workflow version:
- **Idempotency**: check for existing open audit issues before creating new ones
- **Cost controls**: set token budget limits, abort if estimate exceeds threshold
- **Dedup**: cross-reference new findings against existing open security issues
- **Concurrency**: limit to one audit run at a time per repo
