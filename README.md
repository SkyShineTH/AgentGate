# AgentGate

[![CI](https://github.com/SkyShineTH/AgentGate/actions/workflows/ci.yml/badge.svg)](https://github.com/SkyShineTH/AgentGate/actions/workflows/ci.yml)

AgentGate is a provider-agnostic permission gateway for tool-using AI agents.

Let agents propose actions. Let policies decide what can run.

AgentGate sits between an agent runtime and the tools that can read files,
write files, run shell commands, call APIs, or create other side effects. It
turns proposed tool calls into structured requests, evaluates deterministic
policy, queues sensitive actions for human approval, and records the lifecycle
in audit logs.

## What It Demonstrates

- Scoped tool access for file, shell, and future API-style actions
- Deterministic `allow`, `deny`, and `require_approval` policy decisions
- Public/private workspace boundaries with path traversal protection
- Request-specific human approval before approved execution
- SQLite approval queue and JSONL audit log
- Optional adapter helpers that convert external tool-call shapes into the
  canonical `ToolRequest`
- Synthetic PersonalOps demo data only, with no provider SDK dependency

## Quickstart

```bash
python -m pip install -e .[dev]
python -m pytest
```

Evaluate a safe public read:

```bash
agentgate check examples/requests/read_public_file.json
```

Expected decision:

```json
{
  "status": "allow",
  "matched_rule": "public_read_allowed"
}
```

Run the synthetic PersonalOps demo:

```bash
agentgate demo personalops
```

The demo copies sample job-search files into `.agentgate/personalops-demo/`,
then runs static JSON requests through AgentGate:

- public job plan read -> `allow`
- private tracker append -> `require_approval`, then approved as `demo-human`
- private tracker delete -> `deny`
- shell command -> `deny`

## Approval Flow

Approval-required decisions are stored in a local SQLite queue under
`.agentgate/` by default:

```bash
agentgate approvals list
agentgate approvals approve <approval-id> --request-id <request-id>
agentgate approvals reject <approval-id> --request-id <request-id>
agentgate approvals execute <approval-id>
```

Approved execution uses the exact stored request payload. Shell execution and
delete execution are not implemented by the local executor.

## Optional Adapters

Adapter helpers live under `agentgate.adapters` and convert external tool-call
shapes into the canonical `ToolRequest`. The current OpenAI-style adapter
accepts plain function-call dictionaries only and does not require or claim full
OpenAI SDK compatibility.

## Architecture

```text
CLI or adapter
  -> ToolRequest
  -> PolicyEngine
  -> Decision: allow | deny | require_approval
  -> ApprovalQueue or ToolExecutor
  -> AuditLog
```

See [Architecture](docs/ARCHITECTURE.md) and
[Architecture diagram](docs/ARCHITECTURE_DIAGRAM.md).

## Project Context

- [Agent instructions](AGENTS.md)
- [Project context](docs/PROJECT_CONTEXT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Policy model](docs/POLICY_MODEL.md)
- [Security and privacy](docs/SECURITY_PRIVACY.md)
- [Testing and evals](docs/TESTING_EVALS.md)
- [Roadmap](docs/ROADMAP.md)
- [Framework references](docs/FRAMEWORK_REFERENCES.md)
- [Glossary](docs/GLOSSARY.md)
- [Portfolio notes](docs/PORTFOLIO.md)
