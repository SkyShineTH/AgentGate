# Testing and Evals

Last updated: 2026-05-07

## Testing Goal

AgentGate's main behavior is boundary enforcement. Tests should prove that
policy decisions, approvals, workspace boundaries, and audit logs behave
predictably.

Security-sensitive behavior requires regression fixtures. Any discovered
bypass, ambiguous decision, unsafe default, or logging leak should become a
named test case before or alongside the fix.

## Test Categories

### Unit Tests

Cover deterministic core functions:

- schema validation
- path normalization
- policy rule matching
- decision creation
- approval state transitions
- audit event creation
- redaction helpers

### Fixture Tests

Use JSON request fixtures under `examples/requests/` or `tests/fixtures/`.

Each fixture should include:

- input request
- expected decision
- expected matched rule
- expected risk

### Boundary Tests

Required cases:

- allowed public read
- private read requires approval
- write requires approval
- delete denied
- shell denied by default
- path traversal denied
- absolute path outside workspace denied
- unknown tool denied
- malformed request denied
- likely secret denied or redacted

### Approval Tests

Required cases:

- pending approval is created for approval-required requests
- pending approval can be edited only with the same request ID
- edited approval payloads are re-evaluated before approval
- approved request can execute once
- rejected request cannot execute
- edited request records both original and edited payloads
- approval cannot be applied to a different request ID

### Audit Tests

Required cases:

- every decision emits an audit event
- approval transitions emit audit events
- execution result emits an audit event
- logs contain required metadata
- logs do not contain raw secrets

### Adapter Tests

When adapters are added:

- Equivalent tool calls from different frameworks should normalize to the same
  canonical `ToolRequest` shape.
- Adapter failures should not execute tools.
- Provider-specific metadata should not leak into core policy logic.

## Eval Scenarios

Useful named scenarios:

- `safe_public_read`: agent reads a public sample note.
- `private_note_boundary`: agent attempts to read private data.
- `write_requires_approval`: agent proposes a job-tracker update.
- `delete_is_denied`: agent tries to delete a workspace file.
- `path_traversal_denied`: agent attempts `../` escape.
- `secret_redaction`: request contains a fake token and logs redact it.
- `prompt_injection_write`: document instructs agent to ignore policy and write
  outside workspace.

## CI Expectations

Initial CI should run:

```text
python -m pytest
```

Add linting once project tooling is settled.

Do not require network access for the default test suite.

## Definition of Done for Behavior Changes

A behavior change is done when:

- implementation is complete
- tests cover allow/deny/approval path
- docs or examples are updated
- audit behavior is considered
- privacy/logging impact is considered
