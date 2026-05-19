# Audit Lifecycle Demo

Last updated: 2026-05-19

This walkthrough shows the full local lifecycle that the audit report command is
designed to explain:

```text
check -> approval_created -> approve -> execute -> audit report
```

It uses synthetic request data and a disposable state directory under
`.agentgate/`.

## 1. Prepare Demo State

Create isolated workspace and state paths:

```bat
mkdir .agentgate\audit-lifecycle-demo\examples\workspace\public
mkdir .agentgate\audit-lifecycle-demo\examples\workspace\private
```

The request fixture already points at `examples/workspace/private/draft_note.txt`.
The custom workspace flags below make that path resolve inside the disposable
demo directory instead of the tracked examples workspace.

## 2. Create The Approval

Run policy evaluation for the sample private write request:

```bat
agentgate check examples\requests\write_private_note_requires_approval.json --workspace-base .agentgate\audit-lifecycle-demo --public-root .agentgate\audit-lifecycle-demo\examples\workspace\public --private-root .agentgate\audit-lifecycle-demo\examples\workspace\private --approval-db .agentgate\audit-lifecycle-demo\approvals.sqlite --audit-log .agentgate\audit-lifecycle-demo\audit.jsonl
```

Expected decision fields:

```text
status=require_approval
matched_rule=file_write_requires_approval
risk=medium
```

The response includes an `approval_id`. Use that value in the next commands.

## 3. Approve And Execute

Approve the exact request ID:

```bat
agentgate approvals approve <approval-id> --request-id req_write_private_note --approval-db .agentgate\audit-lifecycle-demo\approvals.sqlite --audit-log .agentgate\audit-lifecycle-demo\audit.jsonl
```

Execute the approved request:

```bat
agentgate approvals execute <approval-id> --workspace-base .agentgate\audit-lifecycle-demo --public-root .agentgate\audit-lifecycle-demo\examples\workspace\public --private-root .agentgate\audit-lifecycle-demo\examples\workspace\private --approval-db .agentgate\audit-lifecycle-demo\approvals.sqlite --audit-log .agentgate\audit-lifecycle-demo\audit.jsonl
```

Expected execution result:

```text
result_status=completed
```

The local executor writes only the approved request payload.

## 4. Generate The Audit Report

Use table output for a reviewer-friendly terminal view:

```bat
agentgate audit report --approval-id <approval-id> --approval-db .agentgate\audit-lifecycle-demo\approvals.sqlite --audit-log .agentgate\audit-lifecycle-demo\audit.jsonl --format table
```

Expected sections:

```text
REQUEST SUMMARY
AUDIT EVENTS
DECISION TRAIL
APPROVALS
EXECUTION RESULT
```

The `AUDIT EVENTS` section should show this ordered lifecycle:

```text
policy_decision
approval_created
approval_decided
executed
```

Use JSON output when another tool should consume the report:

```bat
agentgate audit report --request-id req_write_private_note --approval-db .agentgate\audit-lifecycle-demo\approvals.sqlite --audit-log .agentgate\audit-lifecycle-demo\audit.jsonl
```

The same commands can use SQLite-backed audit storage by changing
`--audit-log` to a path such as `.agentgate\audit-lifecycle-demo\audit.sqlite`.

## 5. What This Demonstrates

- The policy decision is explicit before execution.
- Approval is request-specific and tied to `req_write_private_note`.
- Execution happens only after approval and records `result_status`.
- Audit events preserve policy source and workspace source context.
- The lifecycle report turns structured audit events into a portfolio-readable
  feature, not just an implementation detail.
