# Contributing to AgentGate

Thanks for helping improve AgentGate. This project is a provider-agnostic
permission gateway for tool-using AI agents:

```text
Let agents propose actions. Let policies decide what can run.
```

Keep the core focused on policy decisions, approval-based execution, structured
audit logs, and workspace boundaries before actions are executed.

## Local Setup

AgentGate targets Python 3.12+.

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The default test suite must run without API keys, network integrations, OAuth,
or real personal data.

## Development Rules

- Preserve the provider-agnostic core.
- Prefer typed schemas over loose dictionaries.
- Prefer deterministic policy checks over model-judged permissions.
- Do not weaken default policy behavior to make a demo pass.
- Do not add agent framework dependencies to the core package.
- Keep provider/framework-specific behavior behind optional adapters.
- Add or update tests for behavior changes.
- Consider audit, approval, and workspace-boundary impact for every change.
- Keep public docs and examples in English unless a maintainer asks otherwise.

## Data and Secrets

Do not commit:

- real personal notes, resumes, job trackers, or private documents
- API keys, access tokens, cookies, credentials, or private keys
- screenshots or fixtures containing private user data
- production OAuth, Gmail, Calendar, bank, payment, or cloud account data

Use synthetic examples only. If a test needs a token-like value, make it fake
and assert that it is denied or redacted.

## Testing Expectations

When changing behavior, update tests in the same change. Useful coverage areas:

- safe public reads
- private reads requiring approval or being denied by policy
- writes requiring approval
- delete and shell actions denied by default
- path traversal and workspace escape attempts
- approval identity, edit history, and execution lifecycle
- audit events and secret redaction
- adapter behavior that must not override AgentGate policy

## Commit Messages

Use Conventional Commit-style prefixes:

- `feat: add approval history command`
- `fix: validate edited approval identity`
- `docs: clarify approval workflow`
- `test: cover approval audit events`
- `refactor: simplify registry checks`
- `chore: update project tooling`

## Pull Requests

Keep pull requests scoped. Include a short explanation of policy, approval,
audit, and workspace-boundary impact when relevant. Run tests and Ruff before
requesting review.
