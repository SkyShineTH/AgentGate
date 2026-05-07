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

## Phase 1 CLI

AgentGate can evaluate a structured tool request without any provider SDK:

```bash
python -m pip install -e .[dev]
agentgate check examples/requests/read_public_file.json
```

The command prints a JSON policy decision with `status`, `risk`, `reason`,
`matched_rule`, and `request_id`.

Run the Phase 1 tests with:

```bash
python -m pytest
```
