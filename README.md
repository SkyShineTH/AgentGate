# AgentGate

[![CI](https://github.com/SkyShineTH/AgentGate/actions/workflows/ci.yml/badge.svg)](https://github.com/SkyShineTH/AgentGate/actions/workflows/ci.yml)

AgentGate is a provider-agnostic permission gateway for tool-using AI agents.

Let agents propose actions. Let policies decide what can run.

AgentGate sits between an agent runtime and the tools that can read files,
write files, run shell commands, call APIs, or create other side effects. It
turns proposed tool calls into structured requests, evaluates deterministic
policy, queues sensitive actions for human approval, and records the lifecycle
in audit logs.

AgentGate complements built-in agent runtime permissions. A runtime may decide
that an agent is allowed to propose a tool call; AgentGate then evaluates the
specific proposed action as a portable policy, approval, and audit layer before
execution.

## What It Demonstrates

- Scoped tool access for file, shell, and future API-style actions
- Deterministic `allow`, `deny`, and `require_approval` policy decisions
- Public/private workspace boundaries with path traversal protection
- Request-specific human approval before approved execution
- SQLite approval queue and JSONL audit log
- Explicit execution authorization and regression tests for bypass cases
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
agentgate approvals list --status pending --tool file.write
agentgate approvals show <approval-id>
agentgate approvals edit <approval-id> <edited-request-json> --request-id <request-id>
agentgate approvals history <approval-id>
agentgate approvals report <approval-id>
agentgate approvals approve <approval-id> --request-id <request-id>
agentgate approvals reject <approval-id> --request-id <request-id>
agentgate approvals execute <approval-id>
```

An edit replaces the pending approval payload only after the edited request is
validated and re-evaluated by policy. The edited request must keep the same
`request_id` and must still return `require_approval`. Each edit also writes an
`approval_edits` SQLite record with the previous and edited request/decision
payloads, so the approval database preserves the lifecycle. Use
`agentgate approvals show <approval-id>` for the current payload plus edit
summary, or `agentgate approvals history <approval-id>` to inspect full
revisions. `approvals list` can filter by `--status`, `--request-id`,
`--actor`, `--tool`, and `--execution-status`. Approved execution uses the
exact current stored request payload. Shell execution and delete execution are
not implemented by the local executor.

### Local Approval Walkthrough

Use the sample write request to exercise the approval lifecycle:

```bash
agentgate check examples/requests/write_private_note_requires_approval.json
agentgate approvals list --status pending --tool file.write
agentgate approvals show <approval-id>
```

To narrow the pending payload before approval, copy the sample request, keep the
same `request_id`, edit only the intended fields, then submit it:

```bash
cp examples/requests/write_private_note_requires_approval.json edited_request.json
# edit edited_request.json, keeping request_id unchanged
agentgate approvals edit <approval-id> edited_request.json --request-id req_write_private_note
agentgate approvals history <approval-id>
agentgate approvals approve <approval-id> --request-id req_write_private_note
agentgate approvals execute <approval-id>
agentgate approvals report <approval-id>
```

The approval database keeps the current executable payload and the edit history;
the JSONL audit log records the policy, approval, edit, decision, and execution
events. `approvals report` combines those approval, edit-history, and audit
views into one JSON object.

Inspect audit events without opening the JSONL file directly:

```bash
agentgate audit list --request-id req_write_private_note
agentgate audit list --approval-id <approval-id>
agentgate audit list --event-type approval_edited
```

## Policy Profiles

AgentGate uses conservative defaults, but `check` and approval edits can load a
JSON policy profile:

```bash
agentgate check examples/requests/read_private_file_requires_approval.json \
  --policy-config examples/policy/strict.json
```

The current profile supports these fields:

- `private_read`: `require_approval` or `deny`
- `file_write`: `require_approval` or `deny`
- `unknown_tool`, `unknown_action`, `shell_execute`, `file_delete`: `deny`

The deny-only fields are explicit so a local profile can document the posture
without weakening dangerous defaults.

For local workspaces outside the tracked examples, pass workspace roots on the
CLI:

```bash
agentgate check request.json \
  --workspace-base . \
  --public-root ./public \
  --private-root ./private
```

You can also keep workspace and policy defaults in `agentgate.toml`:

```toml
[workspace]
base_dir = "."
public_root = "public"
private_root = "private"

[policy]
private_read = "require_approval"
file_write = "require_approval"
```

Load it with `--config agentgate.toml`. If `agentgate.toml` exists in the
current directory, AgentGate loads it automatically. Explicit CLI workspace
options override `[workspace]`, and `--policy-config` overrides `[policy]`.

## Optional Adapters

Adapter helpers live under `agentgate.adapters` and convert external tool-call
shapes into the canonical `ToolRequest`. The current OpenAI-style adapter
accepts plain function-call dictionaries only and does not require or claim full
OpenAI SDK compatibility. Provider or runtime permission metadata is preserved
for audit context but does not override AgentGate policy decisions.

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

For a complete local owner walkthrough, see
[CLI owner workflow](docs/CLI_OWNER_WORKFLOW.md).

## Security Posture

AgentGate is a permission gateway, not a sandbox. It enforces policy and
approval checks inside its own execution path, but it should be combined with
OS-level isolation, filesystem permissions, network controls, and scoped
credentials for real deployments.

See [Security and privacy](docs/SECURITY_PRIVACY.md).

## Contributing

See [Contributing](CONTRIBUTING.md) for local setup, testing expectations,
commit message rules, and contributor safety guidelines. Security and privacy
reporting guidance lives in [Security policy](SECURITY.md).

## Project Context

- [Agent instructions](AGENTS.md)
- [Project context](docs/PROJECT_CONTEXT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [CLI owner workflow](docs/CLI_OWNER_WORKFLOW.md)
- [Policy model](docs/POLICY_MODEL.md)
- [Security and privacy](docs/SECURITY_PRIVACY.md)
- [Testing and evals](docs/TESTING_EVALS.md)
- [Roadmap](docs/ROADMAP.md)
- [Framework references](docs/FRAMEWORK_REFERENCES.md)
- [Glossary](docs/GLOSSARY.md)
- [Portfolio notes](docs/PORTFOLIO.md)
