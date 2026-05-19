from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentgate.approvals import ApprovalQueue, ApprovalStatus
from agentgate.audit import load_json_lines
from agentgate.cli import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def workspace_args(tmp_path: Path) -> list[str]:
    return [
        "--workspace-base",
        str(tmp_path),
        "--public-root",
        str(tmp_path / "examples" / "workspace" / "public"),
        "--private-root",
        str(tmp_path / "examples" / "workspace" / "private"),
    ]


def test_check_queues_approval_required_request(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )

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
    assert events[0]["payload"]["policy_source"] == "default"
    assert events[0]["payload"]["workspace_source"] == "default"


def test_check_logs_existing_approval_for_duplicate_pending_request(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )

    first = RUNNER.invoke(
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
    second = RUNNER.invoke(
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

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert (
        json.loads(second.output)["approval_id"]
        == json.loads(first.output)["approval_id"]
    )
    assert [event["event_type"] for event in load_json_lines(audit_path)] == [
        "policy_decision",
        "approval_created",
        "policy_decision",
        "approval_existing",
    ]


def test_cli_check_uses_policy_config(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    config_path = tmp_path / "policy.json"
    config_path.write_text('{"private_read": "deny"}', encoding="utf-8")
    request_path = (
        ROOT / "examples" / "requests" / "read_private_file_requires_approval.json"
    )

    result = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--policy-config",
            str(config_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "deny"
    assert output["matched_rule"] == "private_read_denied_by_policy"
    assert ApprovalQueue(db_path).list() == []


def test_cli_check_uses_workspace_root_options(tmp_path: Path) -> None:
    public_root = tmp_path / "examples" / "workspace" / "public"
    private_root = tmp_path / "examples" / "workspace" / "private"
    public_root.mkdir(parents=True)
    private_root.mkdir(parents=True)
    (public_root / "local_note.txt").write_text("synthetic note", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "request_id": "req_local_public_read",
                "actor": "demo-agent",
                "tool": "file.read",
                "action": "read",
                "resource": "examples/workspace/public/local_note.txt",
            }
        ),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            *workspace_args(tmp_path),
            "--approval-db",
            str(tmp_path / "approvals.sqlite"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "allow"
    assert output["matched_rule"] == "public_read_allowed"


def test_cli_check_uses_agentgate_toml_profile(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    public_root = workspace_root / "public"
    private_root = workspace_root / "private"
    public_root.mkdir(parents=True)
    private_root.mkdir(parents=True)
    config_path = tmp_path / "agentgate.toml"
    config_path.write_text(
        """
[workspace]
base_dir = "workspace"
public_root = "public"
private_root = "private"

[policy]
private_read = "deny"
""".strip(),
        encoding="utf-8",
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "request_id": "req_profile_private_read",
                "actor": "demo-agent",
                "tool": "file.read",
                "action": "read",
                "resource": "private/local_note.txt",
            }
        ),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--config",
            str(config_path),
            "--approval-db",
            str(tmp_path / "approvals.sqlite"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "deny"
    assert output["matched_rule"] == "private_read_denied_by_policy"


def test_cli_check_records_profile_sources_in_audit_payload(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    public_root = workspace_root / "public"
    private_root = workspace_root / "private"
    public_root.mkdir(parents=True)
    private_root.mkdir(parents=True)
    config_path = tmp_path / "agentgate.toml"
    config_path.write_text(
        """
[workspace]
base_dir = "workspace"
public_root = "public"
private_root = "private"
""".strip(),
        encoding="utf-8",
    )
    policy_path = tmp_path / "strict.json"
    policy_path.write_text('{"private_read": "deny"}', encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "request_id": "req_profile_source",
                "actor": "demo-agent",
                "tool": "file.read",
                "action": "read",
                "resource": "private/local_note.txt",
            }
        ),
        encoding="utf-8",
    )
    audit_path = tmp_path / "audit.jsonl"

    result = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            "--config",
            str(config_path),
            "--policy-config",
            str(policy_path),
            "--approval-db",
            str(tmp_path / "approvals.sqlite"),
            "--audit-log",
            str(audit_path),
        ],
    )

    assert result.exit_code == 0, result.output
    event = load_json_lines(audit_path)[0]
    payload = event["payload"]
    assert payload["policy_source"] == "policy_config"
    assert payload["policy_path"].endswith("strict.json")
    assert payload["workspace_source"] == "agentgate.toml"
    assert payload["workspace_path"].endswith("agentgate.toml")
    private_root = payload["workspace_roots"]["private_root"].replace("\\", "/")
    assert private_root.endswith("workspace/private")


def test_cli_eval_reports_all_example_requests() -> None:
    result = RUNNER.invoke(app, ["eval"])

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["request_count"] == 12
    assert output["counts"] == {
        "allow": 2,
        "require_approval": 3,
        "deny": 7,
    }
    result_files = {Path(item["file"]).name for item in output["results"]}
    assert "read_public_file.json" in result_files
    assert "append_private_job_tracker_requires_approval.json" in result_files
    public_read = next(
        item
        for item in output["results"]
        if Path(item["file"]).name == "read_public_file.json"
    )
    assert public_read["status"] == "allow"
    assert public_read["matched_rule"] == "public_read_allowed"


def test_cli_eval_can_render_table_for_request_directory() -> None:
    result = RUNNER.invoke(
        app,
        [
            "eval",
            "--requests-path",
            str(ROOT / "examples" / "requests"),
            "--format",
            "table",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "STATUS" in result.output
    assert "read_public_file.json" in result.output
    assert "Counts: allow=1, require_approval=2, deny=5" in result.output


def test_cli_eval_checks_expected_outcomes_manifest() -> None:
    result = RUNNER.invoke(
        app,
        [
            "eval",
            "--expectations",
            str(ROOT / "examples" / "evals" / "default-policy.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["expectation_count"] == 12
    assert output["passed_count"] == 12
    assert output["failed_count"] == 0
    assert all(item["passed"] is True for item in output["results"])


def test_cli_eval_returns_failure_for_mismatched_expectation(tmp_path: Path) -> None:
    manifest_path = tmp_path / "expectations.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "mismatch",
                "cases": [
                    {
                        "file": "examples/requests/read_public_file.json",
                        "status": "deny",
                        "risk": "high",
                        "matched_rule": "wrong_rule",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "eval",
            "--requests-path",
            str(ROOT / "examples" / "requests" / "read_public_file.json"),
            "--expectations",
            str(manifest_path),
        ],
    )

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["failed_count"] == 1
    assert output["results"][0]["passed"] is False
    assert output["results"][0]["failures"] == [
        "status expected deny, got allow",
        "risk expected high, got low",
        "matched_rule expected wrong_rule, got public_read_allowed",
    ]


def test_cli_audit_list_filters_events(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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
    approval_id = json.loads(check.output)["approval_id"]

    by_request = RUNNER.invoke(
        app,
        [
            "audit",
            "list",
            "--request-id",
            "req_write_private_note",
            "--audit-log",
            str(audit_path),
        ],
    )
    by_approval = RUNNER.invoke(
        app,
        [
            "audit",
            "list",
            "--approval-id",
            approval_id,
            "--audit-log",
            str(audit_path),
        ],
    )
    by_type = RUNNER.invoke(
        app,
        [
            "audit",
            "list",
            "--event-type",
            "approval_created",
            "--audit-log",
            str(audit_path),
        ],
    )

    assert by_request.exit_code == 0, by_request.output
    assert by_approval.exit_code == 0, by_approval.output
    assert by_type.exit_code == 0, by_type.output
    assert [event["event_type"] for event in json.loads(by_request.output)] == [
        "policy_decision",
        "approval_created",
    ]
    assert [event["event_type"] for event in json.loads(by_approval.output)] == [
        "approval_created"
    ]
    assert json.loads(by_type.output)[0]["approval_id"] == approval_id


def test_cli_audit_commands_support_sqlite_backend(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.sqlite"
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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
    approval_id = json.loads(check.output)["approval_id"]

    listed = RUNNER.invoke(
        app,
        [
            "audit",
            "list",
            "--request-id",
            "req_write_private_note",
            "--audit-log",
            str(audit_path),
        ],
    )
    report = RUNNER.invoke(
        app,
        [
            "audit",
            "report",
            "--approval-id",
            approval_id,
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
            "--format",
            "table",
        ],
    )

    assert listed.exit_code == 0, listed.output
    assert report.exit_code == 0, report.output
    assert [event["event_type"] for event in json.loads(listed.output)] == [
        "policy_decision",
        "approval_created",
    ]
    assert "REQUEST SUMMARY" in report.output
    assert "approval_created" in report.output
    assert approval_id in report.output


def test_cli_list_filters_approval_records(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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
    request_path = (
        ROOT / "examples" / "requests" / "write_private_note_requires_approval.json"
    )
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


def test_cli_end_to_end_approval_workflow(tmp_path: Path) -> None:
    public_root = tmp_path / "examples" / "workspace" / "public"
    private_root = tmp_path / "examples" / "workspace" / "private"
    public_root.mkdir(parents=True)
    private_root.mkdir(parents=True)
    db_path = tmp_path / "approvals.sqlite"
    audit_path = tmp_path / "audit.jsonl"
    request_payload = {
        "request_id": "req_e2e_write_note",
        "actor": "demo-agent",
        "tool": "file.write",
        "action": "write",
        "resource": "examples/workspace/private/e2e_note.txt",
        "input": {"content": "original e2e content"},
        "metadata": {"scenario": "e2e_approval_workflow"},
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_payload), encoding="utf-8")

    check = RUNNER.invoke(
        app,
        [
            "check",
            str(request_path),
            *workspace_args(tmp_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    assert check.exit_code == 0, check.output
    approval_id = json.loads(check.output)["approval_id"]

    listed = RUNNER.invoke(
        app,
        [
            "approvals",
            "list",
            "--status",
            "pending",
            "--tool",
            "file.write",
            "--approval-db",
            str(db_path),
        ],
    )
    shown = RUNNER.invoke(
        app,
        ["approvals", "show", approval_id, "--approval-db", str(db_path)],
    )
    assert listed.exit_code == 0, listed.output
    assert shown.exit_code == 0, shown.output
    assert json.loads(listed.output)[0]["approval_id"] == approval_id
    assert json.loads(shown.output)["edit_history"]["count"] == 0

    edited_payload = dict(request_payload)
    edited_payload["input"] = {"content": "edited e2e content"}
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
            "req_e2e_write_note",
            "--editor",
            "human-reviewer",
            *workspace_args(tmp_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    history = RUNNER.invoke(
        app,
        ["approvals", "history", approval_id, "--approval-db", str(db_path)],
    )
    assert edited.exit_code == 0, edited.output
    assert history.exit_code == 0, history.output
    assert json.loads(history.output)[0]["edited_request"]["input"] == {
        "content": "edited e2e content"
    }

    approved = RUNNER.invoke(
        app,
        [
            "approvals",
            "approve",
            approval_id,
            "--request-id",
            "req_e2e_write_note",
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    executed = RUNNER.invoke(
        app,
        [
            "approvals",
            "execute",
            approval_id,
            *workspace_args(tmp_path),
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    report = RUNNER.invoke(
        app,
        [
            "approvals",
            "report",
            approval_id,
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    audit_report = RUNNER.invoke(
        app,
        [
            "audit",
            "report",
            "--approval-id",
            approval_id,
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
        ],
    )
    audit_report_table = RUNNER.invoke(
        app,
        [
            "audit",
            "report",
            "--approval-id",
            approval_id,
            "--approval-db",
            str(db_path),
            "--audit-log",
            str(audit_path),
            "--format",
            "table",
        ],
    )

    assert approved.exit_code == 0, approved.output
    assert executed.exit_code == 0, executed.output
    assert report.exit_code == 0, report.output
    assert audit_report.exit_code == 0, audit_report.output
    assert audit_report_table.exit_code == 0, audit_report_table.output
    assert json.loads(executed.output)["result_status"] == "completed"
    assert (private_root / "e2e_note.txt").read_text(encoding="utf-8") == (
        "edited e2e content"
    )
    assert [event["event_type"] for event in load_json_lines(audit_path)] == [
        "policy_decision",
        "approval_created",
        "approval_edited",
        "approval_decided",
        "executed",
    ]
    report_output = json.loads(report.output)
    assert report_output["approval"]["execution_status"] == "completed"
    assert report_output["edit_history"][0]["edited_request"]["input"] == {
        "content": "edited e2e content"
    }
    assert [event["event_type"] for event in report_output["audit_events"]] == [
        "policy_decision",
        "approval_created",
        "approval_edited",
        "approval_decided",
        "executed",
    ]
    audit_report_output = json.loads(audit_report.output)
    assert audit_report_output["request_summary"]["request_id"] == "req_e2e_write_note"
    assert audit_report_output["request_summary"]["approval_ids"] == [approval_id]
    assert [event["event_type"] for event in audit_report_output["audit_events"]] == [
        "policy_decision",
        "approval_created",
        "approval_edited",
        "approval_decided",
        "executed",
    ]
    assert audit_report_output["decision_trail"][0]["risk"] == "medium"
    assert audit_report_output["approvals"][0]["status"] == "approved"
    assert audit_report_output["approvals"][0]["execution_status"] == "completed"
    assert audit_report_output["execution_result"]["result_status"] == "completed"
    assert "REQUEST SUMMARY" in audit_report_table.output
    assert "AUDIT EVENTS" in audit_report_table.output
    assert "DECISION TRAIL" in audit_report_table.output
    assert "APPROVALS" in audit_report_table.output
    assert "EXECUTION RESULT" in audit_report_table.output
    assert "req_e2e_write_note" in audit_report_table.output
    assert approval_id in audit_report_table.output
    assert "completed" in audit_report_table.output
