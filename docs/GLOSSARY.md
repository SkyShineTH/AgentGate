# Glossary

Last updated: 2026-05-07

## Agent

Software that uses a model to decide what to do next and may call tools.

## Tool

A capability exposed to an agent, such as reading a file, writing a document,
running a command, calling an API, or querying a database.

## Tool Request

AgentGate's canonical structured representation of a tool action before it
executes.

## Actor

The agent, user, service account, workflow, or adapter requesting an action.

## Action

The operation being requested, such as `read`, `write`, `append_row`, `delete`,
or `execute`.

## Resource

The target affected by an action, such as a path, API endpoint, database table,
or service.

## Policy

Rules that decide whether a tool request can run.

## Decision

The result of policy evaluation. MVP decisions are `allow`, `deny`, and
`require_approval`.

## Approval

A human decision that allows, rejects, or later edits a specific pending tool
request.

## Grant

A scoped permission. Grants are future-facing and should not be broad in the
MVP.

## Audit Event

A structured record of a request, decision, approval, or execution result.

## Adapter

Integration layer that converts provider-specific or framework-specific tool
calls into AgentGate's canonical `ToolRequest`.

## Provider-Agnostic

Core AgentGate behavior does not require a specific model provider or agent
framework.

## Workspace Boundary

Configured filesystem roots where file actions are allowed to be evaluated.
Requests outside these roots should fail closed.

## Fail Closed

When context is missing or invalid, the system denies execution or requires
approval instead of allowing the tool to run.

