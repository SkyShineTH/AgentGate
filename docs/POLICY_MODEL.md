# Policy Model

Last updated: 2026-05-07

## Policy Goal

Policy decisions are based on normalized action context, not natural-language
intent alone. The policy engine should evaluate structured facts:

- actor
- tool
- action
- resource
- arguments
- workspace root
- environment
- grant state
- risk metadata

Prompts may describe expected behavior, but prompts must not be the enforcement
boundary.

## Decision Statuses

MVP statuses:

- `allow`: execute immediately.
- `deny`: do not execute.
- `require_approval`: store pending approval and wait for human decision.

Possible future statuses:

- `allow_with_redaction`: execute but redact selected outputs.
- `require_elevation`: ask for a narrower additional permission or scope.
- `dry_run_only`: allow simulation but not execution.

Do not add future statuses until tests and docs define their behavior.

## Decision Shape

Every decision should include:

```json
{
  "request_id": "req_...",
  "status": "require_approval",
  "risk": "medium",
  "reason": "File write operations require human approval.",
  "matched_rule": "file_write_requires_approval"
}
```

Required fields:

- `request_id`
- `status`
- `risk`
- `reason`
- `matched_rule`

Optional fields:

- `redactions`
- `approval_id`
- `policy_version`
- `debug`

## Default Posture

Default behavior should be conservative:

- Unknown tools are denied.
- Unknown actions are denied.
- Malformed requests are denied.
- Missing policy context denies execution.
- Write actions require approval.
- Delete actions are denied.
- Shell actions are denied unless explicitly enabled in a local demo policy.
- Path traversal attempts are denied.
- Requests outside configured workspace roots are denied.

## MVP Rule Set

Suggested initial rules:

| Rule ID | Condition | Decision |
|---|---|---|
| `unknown_tool_denied` | tool is not registered | `deny` |
| `malformed_request_denied` | request fails schema validation | `deny` |
| `path_outside_workspace_denied` | normalized path escapes roots | `deny` |
| `public_read_allowed` | read inside public workspace | `allow` |
| `private_read_requires_approval` | read inside private workspace | `require_approval` |
| `file_write_requires_approval` | any file write | `require_approval` |
| `delete_denied` | delete file or directory | `deny` |
| `shell_denied_by_default` | any shell execution | `deny` |
| `secret_input_denied` | likely secret appears in request | `deny` |

## Policy Configuration

Start with code-defined policies and JSON fixtures. Add YAML policy files only
when the behavior is stable enough to express declaratively.

Possible YAML shape:

```yaml
version: 1
defaults:
  unknown_tool: deny
  unknown_resource: deny
rules:
  - id: public_read_allowed
    when:
      tool: file.read
      resource_prefix: examples/workspace/public
    decision: allow
    risk: low
```

## Grants

A grant is a scoped approval. It should include:

- grant ID
- request ID or scope
- actor
- allowed tool/action/resource
- expiry
- approver
- created timestamp
- reason

MVP recommendation: approve exact requests only. Avoid broad reusable grants
until the audit and policy model are mature.

## Policy Versioning

Policy behavior changes should be visible:

- Update tests.
- Update docs.
- Add or update fixtures.
- Include `policy_version` in audit metadata once policy files exist.

