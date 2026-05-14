# Architecture

Last updated: 2026-05-09

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
  - Looks up known tools and supported actions in ToolRegistry.
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
         - Checks ToolRegistry before execution.
         - Calls implemented tools through stable interfaces.
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

- Use `ToolRegistry` to fail closed on unknown tools and unsupported actions.
- Evaluate rules against normalized structured facts.
- Avoid natural-language intent as the only policy input.
- Return typed decisions.
- Make default behavior explicit.

### ApprovalQueue

Responsibilities:

- Store pending approvals.
- Preserve the exact original request payload.
- Allow approve, reject, and edit flows.
- Prevent executing stale or mutated requests accidentally.
- Re-evaluate edited payloads before they can be approved.
- Store edit history with previous and edited request/decision payloads.
- Execute only the currently stored approved payload.

### ToolRegistry

Responsibilities:

- Register tools by stable names.
- Store metadata such as risk level, side-effect category, supported actions,
  and resource types.
- Keep execution handlers separate from policy definitions.

Current implementation:

- Lives in `src/agentgate/registry.py`.
- Defines `ToolDefinition` and `ToolRegistry`.
- Provides the default tool catalog for `file.read`, `file.write`,
  `file.append`, `file.update`, `file.delete`, and `shell.execute`.
- Acts as the source of truth for known tool names and supported actions.
- Can be injected into `PolicyEngine` and `ToolExecutor` for tests or future
  custom tool catalogs.

The registry is metadata only. It does not grant permission by itself and does
not execute tools. Policy still decides `allow`, `deny`, or `require_approval`,
and `ToolExecutor` only implements the local file operations that are safe for
the current demo.

### ToolExecutor

Responsibilities:

- Execute only requests that have an `allow` decision or a valid approval.
- Check that the requested tool and action exist in `ToolRegistry`.
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
- Should policy be expressed as Python rules first or YAML rules first?
- Should shell execution exist in the MVP as denied examples only?
