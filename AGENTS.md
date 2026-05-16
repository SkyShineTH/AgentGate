# AgentGate Agent Instructions

This file is the primary context for AI coding agents working in this
repository. Read it before making changes.

## Project Thesis

AgentGate is a provider-agnostic permission and approval gateway for
tool-using AI agents.

The project should be positioned as AI infrastructure, not as a chatbot,
personal assistant, or security scanner. Its core value is the control layer
between an agent's proposed tool call and the side effect that would happen if
the tool ran.

Short positioning:

```text
Let agents propose actions. Let policies decide what can run.
```

## Target Outcome

Build a portfolio-grade open-source project that demonstrates:

- Scoped tool access for AI agents.
- Policy decisions before tool execution.
- Human approval for sensitive or state-changing actions.
- Structured audit logs for every proposed and executed action.
- Public/private workspace boundaries for personal-agent workflows.
- Repeatable tests and eval scenarios for safe agent behavior.

The first strong demo should use a personal workflow, such as job-search or
document-management automation, but the gateway itself must remain generic.

## Product Boundaries

### In Scope

- A policy engine that returns `allow`, `deny`, or `require_approval`.
- A tool request schema that can represent file, shell, API, and future MCP
  tool calls.
- A tool registry and executor abstraction.
- Approval queue storage and resume flow.
- JSON audit logs or SQLite-backed audit records.
- Local workspace demos using sample data only.
- Tests for policy decisions, approval behavior, audit records, and path
  boundary enforcement.
- Documentation that explains architecture, threat model, non-goals, and demo
  workflows.

### Out of Scope for the MVP

- Autonomous background agents.
- Gmail, Calendar, bank, payment, or production OAuth integrations.
- Enterprise claims such as "zero trust", "SOC-ready", or "military-grade".
- A full replacement for LangGraph, OpenAI Agents SDK, AutoGen, MCP, or any
  other agent framework.
- Real personal data in examples, tests, screenshots, fixtures, or docs.
- Running arbitrary shell commands without explicit policy and approval logic.

## Architecture Direction

The initial architecture should stay simple and inspectable:

```text
User or agent request
  -> Agent adapter or CLI
  -> ToolRequest schema
  -> PolicyEngine
  -> Decision: allow | deny | require_approval
  -> ToolExecutor, ApprovalQueue, or DenialResponse
  -> AuditLog
```

Core components:

- `ToolRequest`: normalized request to perform an action.
- `PolicyEngine`: deterministic rules that evaluate a request.
- `Decision`: typed result with status, reason, matched rule, and risk level.
- `ToolRegistry`: list of known tools and tool metadata.
- `ToolExecutor`: executes only requests that were approved by policy.
- `ApprovalQueue`: stores pending requests and human decisions.
- `AuditLog`: append-only record of requests, decisions, approvals, and
  execution results.
- `WorkspaceBoundary`: validates that file operations stay inside configured
  roots.

Prefer deterministic code for the gateway core. LLM-specific behavior should
live behind adapters.

## Recommended Stack

Default stack unless the user asks otherwise:

- Python 3.12+
- Pydantic for typed schemas.
- Typer for CLI.
- FastAPI later for an HTTP API.
- SQLite for local approval and audit storage.
- pytest for tests.
- Ruff for linting and formatting if added.
- GitHub Actions for CI once the first tests exist.

Do not add an agent framework dependency in the first implementation unless it
is needed for a concrete adapter. The core should work with plain JSON tool
requests first.

## Provider-Agnostic Rule

AgentGate should not depend on a single model provider or agent framework at
the core layer.

Keep these as optional adapters:

- OpenAI Agents SDK adapter.
- LangGraph adapter.
- MCP client/server adapter.
- Custom JSON/HTTP adapter.

The internal policy and approval model must work without any of those
dependencies installed.

## Policy Model

Policy decisions should be explicit and explainable. Every decision should
include:

- `status`: `allow`, `deny`, or `require_approval`.
- `reason`: short human-readable explanation.
- `matched_rule`: rule identifier when applicable.
- `risk`: `low`, `medium`, `high`, or `critical`.
- `request_id`: stable identifier for tracing.

Suggested MVP rules:

- Read operations inside `examples/workspace/public` are allowed.
- Read operations inside private roots require approval or are denied,
  depending on policy.
- Write operations require approval by default.
- Delete operations are denied by default.
- Shell execution is denied by default.
- Any request containing likely secrets is denied or redacted before logging.
- Paths must be normalized and checked against configured workspace roots.

## Approval Workflow

Approval is not the same as allow.

When a request requires approval:

1. Store the original request in the approval queue.
2. Store the policy decision and reason.
3. Return a pending approval response to the caller.
4. Allow a human to approve, reject, or edit the request.
5. Execute only the approved or edited request.
6. Write all steps to the audit log.

Approved actions should be tied to the exact request payload or an edited
payload. Avoid approving vague future permissions in the MVP.

## Audit Requirements

Audit logs are a first-class feature. Record enough information to replay or
debug decisions without storing secrets.

Minimum fields:

- `event_id`
- `timestamp`
- `request_id`
- `actor`
- `tool`
- `action`
- `resource`
- `decision`
- `reason`
- `matched_rule`
- `approval_id`, when applicable
- `result_status`, when executed

Never log API keys, tokens, private credentials, or full sensitive file
contents.

## Security and Privacy Boundaries

This project has security-relevant behavior, but do not overclaim security.
Use precise language such as:

- scoped permissions
- approval workflow
- audit logging
- path boundary enforcement
- secret redaction
- least-privilege tool access

Avoid unsupported claims such as:

- secure by default for production
- zero trust
- enterprise-grade security
- prevents all prompt injection

Treat prompt injection and tool misuse as design risks. Policy enforcement must
be implemented outside the model prompt whenever possible.

## Testing Standards

Tests should focus on behavior and boundaries:

- allow safe reads inside allowed roots
- deny path traversal attempts
- require approval for writes
- deny delete and shell actions by default
- write audit records for allow, deny, approval, and execution paths
- redact likely secrets in logs
- preserve request identity through approval and execution

When adding a feature that changes behavior, add or update tests in the same
change.

## Documentation Standards

Documentation should be concise, specific, and portfolio-ready.

Every major doc should answer:

- What problem does AgentGate solve?
- What is intentionally not included?
- How does the request flow work?
- What can be tested locally?
- What makes this different from a normal agent framework?

Use sample data only. Do not include real private notes, real job tracker data,
API keys, access tokens, or hidden personal documents.

Detailed context lives in:

- `docs/PROJECT_CONTEXT.md`: product thesis, users, MVP, and roadmap summary.
- `docs/ARCHITECTURE.md`: component boundaries and request flow.
- `docs/POLICY_MODEL.md`: decision model, default posture, and rule design.
- `docs/SECURITY_PRIVACY.md`: boundaries, logging, secrets, and claims.
- `docs/TESTING_EVALS.md`: unit tests, fixtures, and regression evals.
- `docs/ROADMAP.md`: phased work and open questions.
- `docs/FRAMEWORK_REFERENCES.md`: informative external ecosystem references.
- `docs/GLOSSARY.md`: shared vocabulary.
- `docs/adr/`: architectural decision records.

## Portfolio Positioning

Preferred wording:

```text
AgentGate is a provider-agnostic permission gateway for tool-using AI agents,
enforcing scoped tool access, approval-based execution, structured audit logs,
and workspace boundaries before actions are executed.
```

Resume-style bullet:

```text
Built AgentGate, a provider-agnostic permission gateway for AI agent runtimes
with scoped tool access, approval-based execution, structured audit logs, and
regression tests for safer file, shell, and API automation.
```

## Development Rules for Agents

- Preserve the provider-agnostic core.
- Keep the MVP small and demonstrable.
- Prefer typed schemas over loose dictionaries.
- Prefer deterministic policy checks over model-judged permissions.
- Do not add network integrations before local workflow tests pass.
- Do not add real user data to examples.
- Do not silently weaken policy defaults to make a demo pass.
- Do not introduce broad dependencies without explaining why they are needed.
- Keep public docs in English unless the user explicitly asks otherwise.
- If a requested change conflicts with these instructions, surface the conflict
  before editing.

## Commit Message Rules

Use Conventional Commit-style prefixes for commits. Examples:

- `feat: add approval history command`
- `fix: validate edited approval identity`
- `docs: clarify approval workflow`
- `test: cover legacy approval database migration`
- `refactor: simplify registry side-effect checks`
- `chore: update project tooling`
