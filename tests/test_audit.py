from __future__ import annotations

from pathlib import Path

from agentgate.audit import AuditLog, load_json_lines, redact
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest


def request() -> ToolRequest:
    return ToolRequest(
        request_id="req_audit",
        actor="demo-agent",
        tool="file.write",
        action="write",
        resource="examples/workspace/private/draft_note.txt",
        input={"content": "synthetic content"},
    )


def decision() -> Decision:
    return Decision(
        request_id="req_audit",
        status=DecisionStatus.REQUIRE_APPROVAL,
        risk=RiskLevel.MEDIUM,
        reason="File write operations require human approval.",
        matched_rule="file_write_requires_approval",
        approval_id="appr_audit",
    )


def test_audit_log_appends_jsonl_events(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLog(log_path)

    audit.record(
        event_type="policy_decision",
        request=request(),
        decision=decision().model_copy(update={"approval_id": None}),
        payload={"input": {"content": "synthetic content"}},
    )
    audit.record(
        event_type="approval_created",
        request=request(),
        decision=decision(),
        approval_id="appr_audit",
    )

    lines = load_json_lines(log_path)

    assert [line["event_type"] for line in lines] == [
        "policy_decision",
        "approval_created",
    ]
    assert all(line["event_id"].startswith("evt_") for line in lines)
    assert lines[0]["request_id"] == "req_audit"
    assert lines[0]["decision"] == "require_approval"
    assert lines[0]["risk"] == "medium"
    assert lines[1]["approval_id"] == "appr_audit"


def test_audit_log_filters_events(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    audit = AuditLog(log_path)
    audit.record(
        event_type="policy_decision",
        request=request(),
        decision=decision().model_copy(update={"approval_id": None}),
        payload={"input": {"content": "synthetic content"}},
    )
    audit.record(
        event_type="approval_created",
        request=request(),
        decision=decision(),
        approval_id="appr_audit",
    )
    other_request = request().model_copy(update={"request_id": "req_other"})
    other_decision = decision().model_copy(
        update={"request_id": "req_other", "approval_id": "appr_other"}
    )
    audit.record(
        event_type="policy_decision",
        request=other_request,
        decision=other_decision,
    )

    assert [
        event.event_type for event in audit.list_events(request_id="req_audit")
    ] == ["policy_decision", "approval_created"]
    assert [
        event.event_type for event in audit.list_events(approval_id="appr_audit")
    ] == ["approval_created"]
    assert [
        event.request_id for event in audit.list_events(event_type="policy_decision")
    ] == ["req_audit", "req_other"]


def test_audit_redacts_likely_secrets() -> None:
    payload = {
        "password": "not-for-logs",
        "nested": {"api_key": "not-for-logs"},
        "token_value": "sk-abcdefghijklmnopqrstuvwxyz",
        "headers": {"Authorization": "Bearer synthetic-token-value"},
        "Cookie": "sessionid=synthetic-session",
    }

    redacted = redact(payload)

    assert redacted["password"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["token_value"] == "[REDACTED]"
    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["Cookie"] == "[REDACTED]"


def test_audit_record_redacts_request_payload_secrets(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    AuditLog(log_path).record(
        event_type="policy_decision",
        request=request(),
        decision=decision(),
        payload={
            "request": {
                "input": {
                    "headers": {"Authorization": "Bearer synthetic-token-value"},
                    "session": "synthetic-session",
                }
            }
        },
    )

    line = load_json_lines(log_path)[0]

    assert line["payload"]["request"]["input"]["headers"]["Authorization"] == (
        "[REDACTED]"
    )
    assert line["payload"]["request"]["input"]["session"] == "[REDACTED]"


def test_audit_record_redacts_top_level_resource_secret(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    request_with_secret_resource = request().model_copy(
        update={
            "resource": (
                "examples/workspace/private/"
                "sk-abcdefghijklmnopqrstuvwxyz"
                "/draft_note.txt"
            )
        }
    )

    AuditLog(log_path).record(
        event_type="policy_decision",
        request=request_with_secret_resource,
        decision=decision(),
    )

    line = load_json_lines(log_path)[0]

    assert line["resource"] == "[REDACTED]"
