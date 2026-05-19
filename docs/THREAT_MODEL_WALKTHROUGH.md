# Threat Model Walkthrough

Last updated: 2026-05-19

This walkthrough uses only checked-in synthetic examples. It shows how
AgentGate turns common tool-use risks into deterministic policy decisions,
approval records, and audit events.

## Scenario 1: Eval Manifest Pass

Run the default examples against the expected outcomes:

```bash
agentgate eval --expectations examples/evals/default-policy.json
```

Expected result:

- all examples pass the manifest
- safe public reads are `allow`
- private reads and writes are `require_approval`
- delete, shell, unknown tool, path traversal, and secret cases are `deny`

Risk covered: policy drift. The manifest makes the default posture repeatable
in local runs and CI.

## Scenario 2: Duplicate Approval

Run the same approval-required request twice against the same local state:

```bash
agentgate check examples/requests/write_private_note_requires_approval.json
agentgate check examples/requests/write_private_note_requires_approval.json
agentgate audit list --request-id req_write_private_note
```

Expected audit sequence:

```text
policy_decision
approval_created
policy_decision
approval_existing
```

Risk covered: duplicate queue entries. AgentGate returns the existing pending
approval for the same request identity instead of creating a second executable
approval.

## Scenario 3: Tampered Execution Payload

The executor authorizes an exact request payload, not just a request ID. If an
approved request is changed after the execution authorization is created, the
executor returns `denied` with:

```text
Execution authorization payload does not match request.
```

Risk covered: approval replay against a modified payload. The approval claim is
bound to the stored request fingerprint, and approved requests can execute only
once.

## Scenario 4: Secret In Metadata Or Resource

Requests containing likely secrets are denied before workspace or tool
execution checks:

```bash
agentgate check examples/requests/secret_input_denied.json
```

Expected decision:

```text
status=deny
matched_rule=secret_input_denied
risk=critical
```

Audit payloads are also passed through deterministic redaction before they are
written to JSONL. This is defense-in-depth; it is not a substitute for keeping
real credentials out of requests and fixtures.

## Inspect The Lifecycle

For any request or approval, build the structured lifecycle report:

```bash
agentgate audit report --request-id req_write_private_note
agentgate audit report --approval-id <approval-id>
```

The report includes the request summary, ordered audit events, decision trail,
approval status, and execution result when present.
