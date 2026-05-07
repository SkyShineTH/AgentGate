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

