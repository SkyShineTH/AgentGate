# Security and Privacy

Last updated: 2026-05-07

## Boundary Statement

AgentGate is a permission gateway, not a full sandbox.

It controls whether a tool request is allowed, denied, or sent for approval.
It should be used with process isolation, filesystem permissions, network
controls, credential scoping, and infrastructure-level access controls
appropriate to the deployment environment.

## What AgentGate Can Help With

- Making tool permissions explicit and testable.
- Denying unknown tools and malformed requests.
- Requiring approval before state-changing actions.
- Enforcing workspace path boundaries.
- Recording structured audit events.
- Redacting obvious secrets from logs.
- Keeping provider-specific tool metadata behind adapters.

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

Initial redaction should catch common high-risk strings:

- `sk-` style API keys
- bearer tokens
- `Authorization` headers
- private key blocks
- password-like key names
- token-like key names

Redaction is defense-in-depth. Do not rely on redaction as the only privacy
control.

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

