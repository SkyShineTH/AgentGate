# AgentGate Research Notes

Last updated: 2026-05-07

These notes summarize the current ecosystem around tool-using agents, approval
workflows, and tool authorization. Use them as context, not as hard product
requirements.

## Key Takeaway

The market already has strong agent frameworks and personal assistants. The
clearest space for AgentGate is a small, provider-agnostic permission gateway
that can sit in front of file, shell, API, or MCP tool execution.

Do not build another general-purpose agent framework. Build the control layer
around tool calls.

## OpenAI Agents SDK

Official docs describe guardrails for checking user input, final output, and
custom function-tool calls. Tool guardrails can run before and after function
tool execution, but some hosted or built-in tools are outside that specific
guardrail pipeline.

AgentGate implication:

- Treat OpenAI Agents SDK as a possible adapter.
- Do not make AgentGate depend on it at the core.
- AgentGate can provide a policy decision service that an OpenAI tool guardrail
  calls before execution.

Sources:

- https://openai.github.io/openai-agents-python/guardrails/
- https://openai.github.io/openai-agents-python/tracing/

## LangGraph and LangChain Human-in-the-Loop

LangGraph documentation emphasizes durable execution, persistence,
checkpointing, replay, and human-in-the-loop workflows. LangChain's HITL
middleware can pause before sensitive tool calls and resume after approve,
edit, or reject decisions.

AgentGate implication:

- LangGraph already handles orchestration and resumable workflows well.
- AgentGate should not rebuild orchestration.
- AgentGate can provide external policy decisions, approval records, and audit
  semantics that plug into LangGraph workflows.

Sources:

- https://docs.langchain.com/oss/python/langgraph/durable-execution
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langchain/human-in-the-loop

## Model Context Protocol

MCP standardizes how clients and servers expose context and tools. The official
authorization specification covers HTTP transport authorization, OAuth-based
flows, audience validation, access tokens, and protected resource metadata.
The security best-practices guidance emphasizes least privilege, scope
minimization, clear consent, sandboxing local servers, and avoiding broad
permissions.

AgentGate implication:

- MCP is a likely integration target, not the core product.
- AgentGate should learn from MCP's least-privilege and consent patterns.
- Future MCP support should avoid token passthrough and should keep scopes
  narrow.

Sources:

- https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
- https://modelcontextprotocol.io/docs/sdk

## Positioning Decision

AgentGate should be described as:

```text
A provider-agnostic permission gateway for tool-using AI agents.
```

Not:

```text
A personal AI assistant.
An agent framework.
A security product.
```

The best portfolio demo is a personal workflow because it is easy to
understand, but the architecture should make it obvious that the gateway can be
used with other agent runtimes.

## Competitive Landscape Notes

Crowded areas:

- General AI assistants.
- Chatbot UIs.
- Agent orchestration frameworks.
- MCP tool servers.
- Prompt-only guardrails.

Less crowded and more portfolio-relevant:

- Provider-agnostic tool permission gateway.
- Request-specific approval workflow.
- Audit-first local agent execution.
- Public/private workspace boundary enforcement.
- Eval tests for tool-call policy behavior.

