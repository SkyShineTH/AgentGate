# Portfolio Notes

Last updated: 2026-05-16

## Short Description

AgentGate is a provider-agnostic permission gateway for tool-using AI agents,
enforcing scoped tool access, approval-based execution, structured audit logs,
and workspace boundaries before actions are executed.

## Reviewer Summary

AgentGate demonstrates infrastructure around agent tool use rather than another
chat interface. The project focuses on the control point before side effects:
normalize a proposed tool call, evaluate deterministic policy, request human
approval when needed, execute only approved actions, and record an audit trail.

## Demo Talking Points

- Safe public reads are allowed immediately.
- Private reads and writes require request-specific approval.
- Deletes and shell execution are denied by default.
- Approved execution uses the exact stored request payload.
- Approval edits preserve previous and edited payloads in SQLite history.
- CLI inspection supports approval list filters, single approval summaries, and
  full edit-history review.
- Audit logs capture policy, approval, and execution lifecycle events.
- SQLite schema versioning keeps local approval storage inspectable as the MVP
  evolves.
- Optional adapters are kept outside the core policy model.

## Resume Bullet

Built AgentGate, a provider-agnostic permission gateway for AI agent runtimes
with scoped tool access, approval-based execution, structured audit logs, and
regression tests for safer file, shell, and API-style automation.

## Non-Claims

Avoid describing AgentGate as production security, zero trust, enterprise-grade,
or a full replacement for agent frameworks. Use precise language: scoped
permissions, approval workflow, audit logging, path boundary enforcement, and
least-privilege tool access.
