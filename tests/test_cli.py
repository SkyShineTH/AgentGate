from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentgate.approvals import ApprovalQueue, ApprovalStatus
from agentgate.audit import load_json_lines
from agentgate.cli import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def test_check_queues_approval_required_request(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"

    result = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "require_approval"
    assert output["approval_id"].startswith("appr_")

    records = ApprovalQueue(db_path).list()
    assert len(records) == 1
    assert records[0].status == ApprovalStatus.PENDING
    assert records[0].request_id == "req_write_private_note"

    events = load_json_lines(audit_path)
    assert [event["event_type"] for event in events] == [
        "policy_decision",
        "approval_created",
    ]


def test_cli_list_filters_approval_records(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    check = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    assert check.exit_code == 0, check.output

    by_request = RUNNER.invoke(
        app,
        [
            "approvals",
            "list",
            "--request-id",
            "req_write_private_note",
            "--approval-db",
            str(db_path),
        ],
    )
    by_tool = RUNNER.invoke(
        app,
        [
            "approvals",
            "list",
            "--tool",
            "file.write",
            "--execution-status",
            "not_executed",
            "--approval-db",
            str(db_path),
        ],
    )
    no_match = RUNNER.invoke(
        app,
        [
            "approvals",
            "list",
            "--actor",
            "other-agent",
            "--approval-db",
            str(db_path),
        ],
    )

    assert by_request.exit_code == 0, by_request.output
    assert by_tool.exit_code == 0, by_tool.output
    assert no_match.exit_code == 0, no_match.output
    assert len(json.loads(by_request.output)) == 1
    assert len(json.loads(by_tool.output)) == 1
    assert json.loads(no_match.output) == []


def test_cli_approve_and_reject_use_request_id_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    check = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    approval_id = json.loads(check.output)["approval_id"]

    mismatch = RUNNER.invoke(
        app,
        [
            "approvals",
            "approve",
            approval_id,
            "--request-id",
            "req_other",
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    assert mismatch.exit_code == 1

    approved = RUNNER.invoke(
        app,
        [
            "approvals",
            "approve",
            approval_id,
            "--request-id",
            "req_write_private_note",
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    assert approved.exit_code == 0, approved.output
    assert json.loads(approved.output)["status"] == "approved"


def test_cli_edit_updates_pending_approval_payload_and_audit(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    check = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    approval_id = json.loads(check.output)["approval_id"]
    original_payload = json.loads(request_path.read_text(encoding="utf-8"))
    edited_payload = dict(original_payload)
    edited_payload["input"] = {"content": "edited synthetic content"}
    edited_path = tmp_path / "edited_request.json"
    edited_path.write_text(json.dumps(edited_payload), encoding="utf-8")

    edited = RUNNER.invoke(
        app,
        [
            "approvals",
            "edit",
            approval_id,
            str(edited_path),
            "--request-id",
            "req_write_private_note",
            "--editor",
            "human-reviewer",
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )

    assert edited.exit_code == 0, edited.output
    output = json.loads(edited.output)
    assert output["request"]["input"] == {"content": "edited synthetic content"}

    record = ApprovalQueue(db_path).get(approval_id)
    assert record.status == ApprovalStatus.PENDING
    assert record.request.input == {"content": "edited synthetic content"}

    events = load_json_lines(audit_path)
    assert [event["event_type"] for event in events] == [
        "policy_decision",
        "approval_created",
        "approval_edited",
    ]
    assert events[-1]["payload"]["edited_by"] == "human-reviewer"


def test_cli_history_lists_approval_edit_payloads(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    check = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    approval_id = json.loads(check.output)["approval_id"]
    original_payload = json.loads(request_path.read_text(encoding="utf-8"))
    edited_payload = dict(original_payload)
    edited_payload["input"] = {"content": "edited synthetic content"}
    edited_path = tmp_path / "edited_request.json"
    edited_path.write_text(json.dumps(edited_payload), encoding="utf-8")

    edit = RUNNER.invoke(
        app,
        [
            "approvals",
            "edit",
            approval_id,
            str(edited_path),
            "--request-id",
            "req_write_private_note",
            "--editor",
            "human-reviewer",
            "--reason",
            "Narrowed content.",
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    assert edit.exit_code == 0, edit.output

    history = RUNNER.invoke(
        app,
        [
            "approvals",
            "history",
            approval_id,
            "--approval-db",
            str(db_path),
        ],
    )

    assert history.exit_code == 0, history.output
    output = json.loads(history.output)
    assert len(output) == 1
    assert output[0]["approval_id"] == approval_id
    assert output[0]["previous_request"]["input"] == original_payload["input"]
    assert output[0]["edited_request"]["input"] == {
        "content": "edited synthetic content"
    }
    assert output[0]["edited_by"] == "human-reviewer"
    assert output[0]["edit_reason"] == "Narrowed content."


def test_cli_show_includes_current_payload_and_edit_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    check = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    approval_id = json.loads(check.output)["approval_id"]
    edited_payload = json.loads(request_path.read_text(encoding="utf-8"))
    edited_payload["input"] = {"content": "edited synthetic content"}
    edited_path = tmp_path / "edited_request.json"
    edited_path.write_text(json.dumps(edited_payload), encoding="utf-8")

    edit = RUNNER.invoke(
        app,
        [
            "approvals",
            "edit",
            approval_id,
            str(edited_path),
            "--request-id",
            "req_write_private_note",
            "--editor",
            "human-reviewer",
            "--reason",
            "Narrowed content.",
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    assert edit.exit_code == 0, edit.output

    show = RUNNER.invoke(
        app,
        [
            "approvals",
            "show",
            approval_id,
            "--approval-db",
            str(db_path),
        ],
    )

    assert show.exit_code == 0, show.output
    output = json.loads(show.output)
    assert output["approval"]["approval_id"] == approval_id
    assert output["approval"]["status"] == "pending"
    assert output["approval"]["execution_status"] == "not_executed"
    assert output["approval"]["request"]["input"] == {
        "content": "edited synthetic content"
    }
    assert output["approval"]["decision"]["status"] == "require_approval"
    assert output["edit_history"]["count"] == 1
    assert output["edit_history"]["edits"][0]["edited_by"] == "human-reviewer"
    assert output["edit_history"]["edits"][0]["edit_reason"] == "Narrowed content."
    assert "previous_request" not in output["edit_history"]["edits"][0]
