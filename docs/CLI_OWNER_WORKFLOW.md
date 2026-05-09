# CLI Owner Workflow

Last updated: 2026-05-09

This guide is for the repository owner running AgentGate locally from a fresh
checkout. It uses synthetic example data only and does not require any provider
SDK, model API key, or agent framework.

## 1. Create a Local Environment

From the repository root:

```bat
cd D:\01_Projects\Active\AgentGate
python -m venv venv
venv\Scripts\activate
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, run the executable directly:

```bat
venv\Scripts\python -m pip install -e ".[dev]"
```

When the virtual environment is active, `python` and `agentgate` should refer
to the project environment.

```bat
python -V
where python
where agentgate
```

## 2. Run the Test Suite

Use the default test command:

```bat
python -m pytest
```

The tests cover schemas, policy decisions, workspace boundaries, approval
state transitions, audit logging, adapters, CLI behavior, and the PersonalOps
demo.

## 3. Check Basic Policy Decisions

Evaluate the core example requests:

```bat
agentgate check examples\requests\read_public_file.json
agentgate check examples\requests\write_private_note_requires_approval.json
agentgate check examples\requests\delete_file_denied.json
```

Expected outcomes:

| Request | Expected status | Meaning |
|---|---|---|
| `read_public_file.json` | `allow` | Public workspace reads are allowed. |
| `write_private_note_requires_approval.json` | `require_approval` | File writes need human approval. |
| `delete_file_denied.json` | `deny` | Delete is denied by default. |

If `agentgate` is not found but the package is installed, use the module form:

```bat
python -m agentgate check examples\requests\read_public_file.json
```

Or call the virtual environment executable directly:

```bat
venv\Scripts\agentgate.exe check examples\requests\read_public_file.json
```

## 4. Inspect the Approval Queue

Approval-required requests are stored in SQLite under `.agentgate\` by
default.

Create or reuse a pending approval:

```bat
agentgate check examples\requests\write_private_note_requires_approval.json
```

List approvals:

```bat
agentgate approvals list
```

The output includes the `approval_id`, `request_id`, approval status, stored
request payload, decision, and execution status.

## 5. Edit a Pending Approval

Use this flow when the proposed action is directionally acceptable but the
stored payload should be narrowed before approval.

1. Copy an existing approval-required request JSON to a temporary file.
2. Keep the same `request_id`.
3. Change only the intended fields, such as `input.content`.
4. Submit the edited request:

```bat
agentgate approvals edit <approval-id> <edited-request-json> --request-id <request-id>
```

AgentGate validates the edited request and runs policy again. The edit is
accepted only when the edited request still evaluates to `require_approval`.

This is intentional: editing must not turn a pending approval into a silent
allow or a denied action.

## 6. Approve or Reject

Approve a pending request-specific approval:

```bat
agentgate approvals approve <approval-id> --request-id <request-id>
```

Reject a pending approval:

```bat
agentgate approvals reject <approval-id> --request-id <request-id>
```

The `--request-id` option is a guard. It prevents a human action from being
accidentally applied to the wrong approval record.

## 7. Execute an Approved Request

After approval:

```bat
agentgate approvals execute <approval-id>
```

Execution uses the exact request payload currently stored in the approval
record. If the approval was edited before approval, the edited payload is what
executes.

Approved requests are claimed atomically and can execute only once.

## 8. Inspect Audit Logs

Audit events are written to JSONL under `.agentgate\audit.jsonl` by default:

```bat
type .agentgate\audit.jsonl
```

Common event types:

- `policy_decision`
- `approval_created`
- `approval_edited`
- `approval_decided`
- `executed`

Audit payloads are redacted before writing. Do not use real secrets or real
personal data in examples, tests, or demos.

## 9. Run the PersonalOps Demo

Run the synthetic local workflow:

```bat
agentgate demo personalops
```

The demo creates runtime state in:

```text
.agentgate\personalops-demo\
```

It demonstrates:

- allowed public read
- approval-required private tracker append
- denied private tracker delete
- denied shell command

Inspect demo audit logs:

```bat
type .agentgate\personalops-demo\audit.jsonl
```

Inspect demo approvals:

```bat
agentgate approvals list --approval-db .agentgate\personalops-demo\approvals.sqlite
```

## 10. Reset Local Runtime State

The `.agentgate\` directory contains local runtime artifacts only: approval
SQLite databases, audit logs, and demo copied workspaces.

To start over, close any process using the SQLite database and remove the
runtime directory:

```bat
rmdir /s /q .agentgate
```

Do not delete files under `examples\workspace\` or `examples\personalops\`
unless you intentionally want to change source fixtures.

## 11. Troubleshooting

### `agentgate` is not recognized

Use the module form:

```bat
python -m agentgate check examples\requests\read_public_file.json
```

Or reinstall in the active virtual environment:

```bat
python -m pip install -e ".[dev]"
```

### `.[dev]` install fails

Make sure the command is exactly:

```bat
python -m pip install -e ".[dev]"
```

The dot must come before `[dev]`.

### Approval edit is rejected

Check these conditions:

- The approval is still `pending`.
- The edited JSON is a valid `ToolRequest`.
- The edited JSON has the same `request_id`.
- The edited request still evaluates to `require_approval`.

### Shell and delete do not execute

That is expected. Shell execution and delete execution are denied by policy and
not implemented by the local executor.
