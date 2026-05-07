# AgentGate

Provider-agnostic permission gateway for tool-using AI agents.

AgentGate is an early-stage AI infrastructure project. The goal is to let
agents propose actions while a policy gateway decides whether each tool call is
allowed, denied, or requires human approval before execution.

## Project Context

- [Agent instructions](AGENTS.md)
- [Project context](docs/PROJECT_CONTEXT.md)
- [Research notes](docs/RESEARCH_NOTES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Policy model](docs/POLICY_MODEL.md)
- [Security and privacy](docs/SECURITY_PRIVACY.md)
- [Testing and evals](docs/TESTING_EVALS.md)
- [Roadmap](docs/ROADMAP.md)
- [Framework references](docs/FRAMEWORK_REFERENCES.md)
- [Glossary](docs/GLOSSARY.md)

## CLI

AgentGate can evaluate a structured tool request without any provider SDK:

```bash
python -m pip install -e .[dev]
agentgate check examples/requests/read_public_file.json
```

The command prints a JSON policy decision with `status`, `risk`, `reason`,
`matched_rule`, and `request_id`.

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

## PersonalOps Demo

Run the synthetic job-search workflow demo:

```bash
agentgate demo personalops
```

The demo copies sample public/private workspace files into
`.agentgate/personalops-demo/`, evaluates static request JSON, auto-approves one
private tracker append as `demo-human`, and writes a JSONL audit log for the
policy, approval, and execution lifecycle.

Run the tests with:

```bash
python -m pytest
```
