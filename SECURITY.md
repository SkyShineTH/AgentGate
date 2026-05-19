# Security Policy

AgentGate is a permission gateway, not a full sandbox. It evaluates structured
tool requests before execution, queues sensitive actions for approval, records
audit events, and enforces workspace path boundaries inside its own execution
path.

Use AgentGate with operating-system isolation, filesystem permissions, network
controls, and scoped credentials for real deployments.

## Supported Versions

AgentGate is currently an early MVP. Security and privacy fixes target the
current `main` branch until versioned releases exist.

## Reporting Security or Privacy Issues

Do not include secrets, private documents, credentials, exploit payloads, or
real personal data in a public issue.

Preferred reporting path:

1. Use GitHub private vulnerability reporting if it is enabled for the
   repository.
2. If private reporting is not available, open a minimal public issue asking
   for maintainer contact and omit sensitive details.

For lower-risk design concerns, use the Security/privacy review issue template
and include only synthetic examples.

## In Scope

- policy bypasses
- approval identity or execution lifecycle bugs
- path boundary bypasses
- audit log secret leakage
- unsafe defaults for shell, delete, or state-changing actions
- adapter behavior that grants permissions outside AgentGate policy

## Out of Scope

- claims that AgentGate replaces OS sandboxing or cloud IAM
- issues requiring real user data to reproduce
- production OAuth, Gmail, Calendar, bank, or payment integrations
- denial of service against local demo-only state files

## Safe Disclosure Expectations

Use synthetic examples. If a reproduction needs a key or token pattern, use a
fake value and clearly mark it as synthetic.
