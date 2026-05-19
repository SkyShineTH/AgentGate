# Security and Privacy

Last updated: 2026-05-07

## Boundary Statement

AgentGate is a permission gateway, not a full sandbox.

It controls whether a tool request is allowed, denied, or sent for approval.
It should be used with process isolation, filesystem permissions, network
controls, credential scoping, and infrastructure-level access controls
appropriate to the deployment environment.

AgentGate is also not a replacement for built-in agent runtime permissions. It
is a second policy and audit layer for proposed actions that a runtime or
adapter has already normalized into `ToolRequest`.

## Current Trust Boundaries

AgentGate assumes the caller can submit untrusted tool requests, but the Python
process running AgentGate is trusted application code.

Current enforced boundaries:

- Policy decisions happen before tool execution.
- The local executor requires an explicit authorization marker.
- Approval-required requests are stored by exact request payload.
- Approved requests are claimed before execution and can execute only once.
- File resources are normalized and checked against configured public/private
  workspace roots.
- Audit payloads pass through shared redaction before JSONL write.

Current non-boundaries:

- AgentGate does not isolate the Python process from the operating system.
- AgentGate does not prevent direct filesystem access by code that bypasses its
  executor.
- AgentGate does not authenticate CLI users.
- AgentGate does not encrypt local SQLite or JSONL files.
- AgentGate does not provide cross-host distributed locking.
- AgentGate does not validate the semantic safety of file contents read by an
  agent.

## Threat Model Summary

| Risk | Control | Test coverage | Residual risk |
|---|---|---|---|
| Path traversal or workspace escape | `WorkspaceBoundary` normalizes paths and rejects `..` and paths outside configured roots. | `test_path_traversal_denied`, `test_path_outside_workspace_denied` | OS-level permissions are still required for code that bypasses AgentGate. |
| Wrong or stale approval applied to another request | Approval operations require the expected `request_id`; edited requests and decisions must keep the same request identity. | approval request-id guard and edit identity tests | Local operators can still approve a bad but correctly identified request. |
| Direct executor bypass | `ToolExecutor.execute()` requires explicit authorization and checks registered tools/actions before file operations. | direct unauthorized executor and custom registry tests | Code with direct filesystem access can bypass the Python executor entirely. |
| Secret leakage in audit logs | Audit payloads pass through deterministic redaction before JSONL write. | audit redaction tests | Pattern-based redaction can miss unknown secret formats. |
| Runtime permission metadata bypass | Adapter metadata is preserved as context but policy ignores it as an authorization source. | runtime permission handoff adapter test | Full provider SDK behavior is not claimed until adapter-specific tests exist. |
| Local audit or SQLite tampering | Approval and audit records are structured and inspectable, with SQLite schema versioning for the approval store. | approval persistence, edit history, and schema version tests | Local users with filesystem access can modify or delete local state files. |
| Prompt injection causing unsafe tool calls | Policy enforcement happens outside prompts; state-changing file actions require approval and deletes/shell are denied by default. | policy, approval, and denied-action tests | AgentGate does not classify arbitrary document content as safe or unsafe. |

For a concrete local scenario walkthrough, see
[Threat model walkthrough](THREAT_MODEL_WALKTHROUGH.md).

## What AgentGate Can Help With

- Making tool permissions explicit and testable.
- Denying unknown tools and malformed requests.
- Requiring approval before state-changing actions.
- Enforcing workspace path boundaries.
- Recording structured audit events.
- Redacting obvious secrets from logs.
- Keeping provider-specific tool metadata behind adapters.
- Preserving runtime permission context without letting it override policy.

## What AgentGate Does Not Guarantee

- It does not make untrusted tools safe.
- It does not prevent all prompt injection.
- It does not replace operating-system sandboxing.
- It does not replace cloud IAM or network controls.
- It does not certify compliance.
- It does not guarantee that an allowed tool output is safe to trust.

## Sensitive Data Rules

Never commit or log:

- API keys
- access tokens
- refresh tokens
- cookies
- private keys
- passwords
- real personal documents
- real job tracker data
- private interview notes
- full sensitive file contents

Use synthetic examples under `examples/`.

## Logging Rules

Audit logs should be useful without storing sensitive payloads.

Log:

- request ID
- actor
- tool
- action
- resource identifier
- decision
- reason
- matched rule
- timestamps
- execution status

Avoid logging:

- raw credentials
- full prompts containing private data
- authorization headers
- full private file contents
- external API responses that may contain PII

## Redaction

Redaction should catch common high-risk strings and key names:

- `sk-` style API keys
- bearer tokens
- basic auth credentials
- AWS-style access key IDs
- `Authorization` headers
- cookies and session fields
- private key blocks
- password-like key names
- token-like key names

Redaction is defense-in-depth. Do not rely on redaction as the only privacy
control.

## Known Limitations

- The local executor is intentionally narrow and should not be treated as an OS
  sandbox.
- The SQLite approval queue is suitable for local demos and tests, not a
  distributed production approval system.
- Audit logs are append-only by convention in this implementation, but local
  users with filesystem access can still modify or delete them.
- Secret detection uses deterministic patterns and may miss unknown secret
  formats or over-redact benign fields.
- Approval is request-specific; broad reusable grants are intentionally not
  implemented.
- Optional adapters normalize tested dictionary shapes only. They do not prove
  compatibility with full provider SDK runtimes.
- Runtime permission metadata is treated as context. It is not a policy bypass.

## Prompt Injection Risk

Prompt injection is relevant because agents may read documents and then call
tools. AgentGate should treat model output and tool arguments as untrusted.

Preferred mitigations:

- Enforce policy outside the model prompt.
- Require approval for state-changing actions.
- Deny dangerous actions by default.
- Keep tool scopes narrow.
- Use synthetic fixtures to test known bypass patterns.

## Claims Policy

Use precise claims:

- "scoped tool access"
- "approval-based execution"
- "audit logging"
- "workspace boundary checks"
- "provider-agnostic policy gateway"

Avoid unsupported claims:

- "secure by default in production"
- "zero trust"
- "enterprise-grade"
- "prevents prompt injection"
- "compliance-ready"

## External Integrations

When adding integrations:

- Keep credentials out of fixtures.
- Prefer read-only scopes first.
- Add tests for insufficient permissions.
- Avoid token passthrough.
- Document the integration's trust boundary.
- Make telemetry opt-in and easy to disable.
