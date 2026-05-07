# ADR 0001: Keep the Core Provider-Agnostic

Date: 2026-05-07

## Status

Accepted

## Context

AgentGate sits near several fast-moving ecosystems:

- OpenAI Agents SDK
- LangGraph and LangChain
- Model Context Protocol
- other agent frameworks and tool runtimes

Those systems provide useful patterns for guardrails, human-in-the-loop
workflows, tracing, and tool protocols. However, AgentGate's portfolio and
technical value depends on being a reusable permission gateway rather than a
thin wrapper around one provider SDK.

## Decision

AgentGate's core domain model will be provider-agnostic.

The core package must define its own canonical request, decision, approval, and
audit models. External frameworks may be supported through adapters, but they
must not dictate core behavior or become required dependencies for policy
evaluation.

## Consequences

Positive:

- The core can be tested without API keys or network access.
- Policy behavior remains stable across framework changes.
- AgentGate can integrate with multiple runtimes over time.
- Portfolio positioning stays focused on infrastructure.

Tradeoffs:

- Adapters require explicit mapping code.
- The project must maintain its own canonical schema.
- Some provider-native features may not map perfectly into the MVP model.

## Implementation Guidance

- Put provider-specific code in adapter modules.
- Keep tests for core policy free from provider SDK imports.
- Mark external references as informative unless compatibility tests exist.
- Prefer JSON fixtures for canonical tool requests.

