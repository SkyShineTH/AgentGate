# Architecture

Last updated: 2026-05-07

## Architecture Goal

AgentGate is a boundary layer between an agent runtime and the tools that can
create side effects.

The core domain model must not depend on provider-native tool-call schemas.
Provider and framework integrations belong in adapters. The canonical tool
request format is the internal contract used by policy evaluation, approval,
execution, audit logging, and tests.

See [Architecture diagram](ARCHITECTURE_DIAGRAM.md) for the current request
lifecycle view.

## System Flow

```text
Agent runtime, CLI, or API caller
  |
  v
Adapter
  - Converts provider/framework-specific tool calls into ToolRequest.
  - Optional. The core can receive ToolRequest directly.
  |
  v
Request Normalizer
  - Validates required fields.
  - Normalizes paths and resources.
  - Adds request IDs and timestamps.
  - Rejects malformed requests before policy evaluation.
  |
  v
Policy Engine
  - Evaluates deterministic rules.
  - Returns allow, deny, or require_approval.
  - Provides reason, risk, and matched rule.
  |
  +--> Denial Response
  |
  +--> Approval Queue
  |      - Stores pending requests.
  |      - Waits for approve, reject, or edit.
  |      - Emits audit events for human decisions.
  |
  +--> Tool Dispatcher
         - Executes only allowed or approved requests.
         - Calls registered tools through stable interfaces.
         - Returns execution result.

Every stage writes to Audit Log with redaction.
```

## Core Components

### ToolRequest

Canonical request to perform an action. It should be serializable to JSON and
stable enough for fixtures.

Key fields:

- `request_id`
- `actor`
- `tool`
- `action`
- `resource`
- `input`
- `metadata`
- `created_at`

### RequestNormalizer

Responsibilities:

- Parse incoming JSON or adapter output.
- Validate required fields.
- Normalize resource identifiers.
- Resolve file paths without following unsafe assumptions.
- Attach request ID when missing.
- Fail closed on malformed input.

### PolicyEngine

Responsibilities:

- Evaluate rules against normalized structured facts.
- Avoid natural-language intent as the only policy input.
- Return typed decisions.
- Make default behavior explicit.

### ApprovalQueue

Responsibilities:

- Store pending approvals.
- Preserve the exact original request payload.
- Allow approve, reject, and later edit flows.
- Prevent executing stale or mutated requests accidentally.

### ToolRegistry

Responsibilities:

- Register tools by stable names.
- Store metadata such as risk level, side-effect category, supported actions,
  and resource types.
- Keep execution handlers separate from policy definitions.

### ToolDispatcher

Responsibilities:

- Execute only requests that have an `allow` decision or a valid approval.
- Return structured results.
- Avoid logging raw sensitive outputs.

### AuditLog

Responsibilities:

- Record request lifecycle events.
- Redact secrets and sensitive payloads.
- Preserve enough metadata to debug and demonstrate behavior.

## Data Stores

MVP:

- JSONL audit log for simple inspectability.
- SQLite approval store for pending and decided requests.

Later:

- Pluggable audit sinks.
- Postgres-backed approval queue.
- Trace export adapters.

## Dependency Boundaries

Core package:

- No provider SDK dependency.
- No agent framework dependency.
- No network dependency for tests.

Adapters:

- May depend on OpenAI Agents SDK, LangGraph, MCP SDK, or other frameworks.
- Must convert external tool-call shapes into the canonical `ToolRequest`.
- Must not alter core policy behavior.

## Failure Posture

Fail closed when:

- A request is malformed.
- A tool is unknown.
- A resource cannot be normalized.
- A policy file cannot be parsed.
- An approval record is missing or expired.
- A configured policy store is unavailable.

Failing closed means returning `deny` or `require_approval`, never executing the
tool silently.

## Open Questions

- Should the first audit store be JSONL only, SQLite only, or both?
- Should `require_approval` support request edits in the first release or only
  approve/reject?
- Should policy be expressed as Python rules first or YAML rules first?
- Should shell execution exist in the MVP as denied examples only?
