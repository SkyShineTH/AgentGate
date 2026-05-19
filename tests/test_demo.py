from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentgate.approvals import ApprovalQueue, ApprovalStatus, ExecutionStatus
from agentgate.audit import load_json_lines
from agentgate.cli import app
from agentgate.demo import PERSONALOPS_ROOT, run_personalops_demo


def test_personalops_demo_runs_gateway_lifecycle(tmp_path: Path) -> None:
    state_dir = tmp_path / "personalops-demo"

    report = run_personalops_demo(state_dir=state_dir)

    steps = {step.name: step for step in report.steps}
    assert steps["safe_public_job_plan_read"].status == "allow"
    assert steps["safe_public_job_plan_read"].execution_status == "completed"
    assert steps["approved_private_tracker_update"].status == "require_approval"
    assert steps["approved_private_tracker_update"].approval_status == "approved"
    assert steps["approved_private_tracker_update"].execution_status == "completed"
    assert steps["delete_private_tracker_denied"].status == "deny"
    assert steps["delete_private_tracker_denied"].execution_status is None
    assert steps["shell_command_denied"].status == "deny"
    assert steps["shell_command_denied"].execution_status is None

    tracker = state_dir / "examples" / "workspace" / "private" / "job-tracker.csv"
    assert "Contoso Analytics" in tracker.read_text(encoding="utf-8")

    source_tracker = PERSONALOPS_ROOT / "workspace" / "private" / "job-tracker.csv"
    assert "Contoso Analytics" not in source_tracker.read_text(encoding="utf-8")


def test_personalops_demo_records_approval_and_audit_lifecycle(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "personalops-demo"

    report = run_personalops_demo(state_dir=state_dir)

    approvals = ApprovalQueue(Path(report.approval_db)).list()
    assert len(approvals) == 1
    assert approvals[0].status == ApprovalStatus.APPROVED
    assert approvals[0].execution_status == ExecutionStatus.COMPLETED
    assert approvals[0].request_id == "req_personalops_append_tracker"

    events = load_json_lines(Path(report.audit_log))
    event_types = [event["event_type"] for event in events]
    assert event_types.count("policy_decision") == 4
    assert event_types.count("approval_created") == 1
    assert event_types.count("approval_decided") == 1
    assert event_types.count("executed") == 2


def test_personalops_demo_can_leave_write_pending(tmp_path: Path) -> None:
    state_dir = tmp_path / "personalops-demo"

    report = run_personalops_demo(state_dir=state_dir, auto_approve=False)

    steps = {step.name: step for step in report.steps}
    assert steps["approved_private_tracker_update"].approval_status == "pending"
    assert steps["approved_private_tracker_update"].execution_status is None

    tracker = state_dir / "examples" / "workspace" / "private" / "job-tracker.csv"
    assert "Contoso Analytics" not in tracker.read_text(encoding="utf-8")


def test_personalops_demo_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    state_dir = tmp_path / "personalops-demo"

    result = runner.invoke(
        app,
        ["demo", "personalops", "--state-dir", str(state_dir)],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["state_dir"] == str(state_dir.resolve(strict=False))
    assert len(output["steps"]) == 4
    assert output["steps"][1]["status"] == "require_approval"
    assert output["steps"][1]["approval_status"] == "approved"
