# AgentGate Project Context

Last updated: 2026-05-07

## One-Line Summary

AgentGate is a provider-agnostic permission and approval gateway for
tool-using AI agents.

## Why This Project Exists

Modern AI agents can call tools that read files, modify documents, run shell
commands, call APIs, and interact with external systems. The useful part is the
tool use. The risky part is also the tool use.

AgentGate explores a narrow infrastructure layer:

```text
Before an agent action runs, convert it into a structured request, evaluate it
against policy, optionally ask for human approval, and record the result.
```

This makes the project different from a normal AI assistant. The assistant is a
use case. The gateway is the product.

## Target Users

- Developers building local or personal AI agents.
- Builders experimenting with tool-calling workflows.
- Teams that want a small, inspectable approval layer before adopting heavier
  agent orchestration systems.
- Portfolio reviewers evaluating AI infrastructure, platform engineering, and
  safe automation work.

## MVP User Story

As a developer building a personal AI agent, I want every proposed tool call to
pass through a policy gateway so that reads, writes, shell commands, and API
actions are allowed, denied, or sent for approval before anything happens.

## Core Concepts

### Tool Request

A normalized representation of an action an agent wants to perform.

Example:

```json
{
  "actor": "demo-agent",
  "tool": "file.write",
  "action": "append_row",
  "resource": "examples/workspace/private/job-tracker.csv",
  "input": {
    "row": {
      "company": "Example Co",
      "status": "draft"
    }
  }
}
```

### Policy Decision

A deterministic result produced before execution:

```json
{
  "status": "require_approval",
  "risk": "medium",
  "reason": "File write operations require human approval.",
  "matched_rule": "file_write_requires_approval"
}
```

### Approval

A human decision attached to a specific pending request. Approval should be
request-specific, not a blanket grant.

### Audit Event

An append-only record of the request lifecycle:

```text
request_received -> policy_decision -> approval_created -> approval_decided -> executed
```

## MVP Architecture

```text
CLI or adapter
  |
  v
ToolRequest schema
  |
  v
PolicyEngine -------> AuditLog
  |
  +-- allow ----------> ToolExecutor ------> AuditLog
  |
  +-- deny -----------> DenialResponse ----> AuditLog
  |
  +-- require_approval -> ApprovalQueue ---> AuditLog
```

## Suggested Repository Structure

```text
agentgate/
  AGENTS.md
  README.md
  pyproject.toml
  src/
    agentgate/
      __init__.py
      schemas.py
      policy.py
      tools.py
      approvals.py
      audit.py
      workspace.py
      cli.py
  tests/
    test_policy.py
    test_workspace.py
    test_approvals.py
    test_audit.py
  examples/
    requests/
      read_public_file.json
      write_private_note.json
      delete_file_denied.json
    workspace/
      public/
      private/
  docs/
    PROJECT_CONTEXT.md
    RESEARCH_NOTES.md
    ARCHITECTURE.md
```

## MVP Roadmap

### Phase 1: Core Gateway

- Define Pydantic schemas for tool requests and decisions.
- Implement file-oriented policy rules.
- Add workspace path normalization and boundary checks.
- Add JSONL audit logging.
- Add CLI command to evaluate a request JSON file.
- Add tests for allow, deny, and approval decisions.

Done when:

- `agentgate check examples/requests/read_public_file.json` returns `allow`.
- `agentgate check examples/requests/write_private_note.json` returns
  `require_approval`.
- `agentgate check examples/requests/delete_file_denied.json` returns `deny`.
- Tests cover the same cases.

### Phase 2: Approval Queue

- Store pending approvals in SQLite.
- Add CLI commands to list, approve, reject, and execute approved requests.
- Tie approval decisions to immutable request IDs.
- Add audit events for every approval transition.

Done when:

- A write request is stored as pending.
- A human can approve it through CLI.
- Only the approved request can execute.
- Rejected requests do not execute.

### Phase 3: PersonalOps Demo

- Add sample job-search or document-workspace data.
- Show an agent-like workflow using static JSON requests first.
- Add a small demo script that proposes actions and routes them through
  AgentGate.
- Keep all demo data synthetic.

Done when:

- The demo shows safe reads, approval-required writes, and denied sensitive
  operations.
- The audit log tells the full story of the run.

### Phase 4: Agent Adapters

- Add one optional adapter at a time.
- Start with the adapter that creates the clearest demo.
- Keep the core importable and testable without provider SDKs.

Candidate adapters:

- OpenAI Agents SDK function-tool guardrail adapter.
- LangGraph human-in-the-loop middleware integration.
- MCP server/client policy bridge.

## Differentiation

AgentGate should not compete with full agent frameworks. Instead, it should
complement them.

| Category | Examples | AgentGate's Role |
|---|---|---|
| Agent SDK | OpenAI Agents SDK, AutoGen | External execution-control layer |
| Orchestration | LangGraph | Policy and approval gateway before side effects |
| Tool protocol | MCP | Policy bridge for tool calls |
| Personal assistant | ChatGPT, Gemini, Siri | Infrastructure behind a controlled personal-agent demo |

## Naming and Language

Use:

- permission gateway
- approval runtime
- execution-control layer
- scoped tool access
- structured audit logs
- provider-agnostic

Avoid:

- security scanner
- zero trust gateway
- enterprise-grade security
- autonomous secretary
- chatbot framework

## Design Principles

- Policy enforcement lives outside prompts.
- Core logic is deterministic.
- Dangerous defaults should fail closed.
- Approval should be explicit and request-specific.
- Audit logs should be useful without leaking secrets.
- Examples should be realistic but synthetic.
- Integrations should be optional.

## Initial Acceptance Criteria

- A new contributor can understand the project from README + AGENTS +
  `docs/PROJECT_CONTEXT.md`.
- A coding agent can implement Phase 1 without asking what the project is.
- The repo clearly communicates that AgentGate is infrastructure, not a
  personal assistant clone.
- The MVP can be demonstrated locally without API keys.

