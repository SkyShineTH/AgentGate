# Framework References

Last updated: 2026-05-07

External frameworks are cited for interoperability and shared vocabulary. They
are not normative sources for AgentGate's core architecture unless an ADR
explicitly adopts a specific behavior.

## Reference Policy

When referencing external frameworks:

- Use official documentation when possible.
- Record access date or last review date.
- Treat references as informative unless compatibility is implemented and
  tested.
- Keep provider/framework-specific behavior behind adapters.
- Avoid claims like "MCP-compatible", "LangGraph-compatible", or
  "OpenAI-compatible" until tests cover that claim.

## OpenAI Agents SDK

Reviewed: 2026-05-07

Relevant concepts:

- agent guardrails
- tool guardrails
- tracing
- function-tool invocation checks

AgentGate use:

- Informative reference for tool-call guardrail patterns.
- Possible future adapter where a tool guardrail calls AgentGate policy before
  execution.

Sources:

- https://openai.github.io/openai-agents-python/guardrails/
- https://openai.github.io/openai-agents-python/tracing/

## LangGraph and LangChain HITL

Reviewed: 2026-05-07

Relevant concepts:

- durable execution
- persistence/checkpointing
- human-in-the-loop interrupts
- approve, edit, and reject decisions
- resumable workflows

AgentGate use:

- Informative reference for approval and resume patterns.
- Possible future bridge that uses AgentGate decisions inside LangGraph HITL
  workflows.

Sources:

- https://docs.langchain.com/oss/python/langgraph/durable-execution
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langchain/human-in-the-loop

## Model Context Protocol

Reviewed: 2026-05-07

Relevant concepts:

- tool protocol
- resources and tools
- authorization for HTTP transports
- least-privilege scopes
- consent and local-server safety
- token audience validation

AgentGate use:

- Informative reference for future MCP policy bridge.
- Do not implement MCP compatibility until tests verify request handling.

Sources:

- https://modelcontextprotocol.io/docs/sdk
- https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices

## Design Implication

AgentGate should be a narrow control layer:

```text
External agent framework -> adapter -> AgentGate policy/approval/audit -> tool
```

It should not duplicate full orchestration, memory, model routing, or tool
protocol ecosystems.

