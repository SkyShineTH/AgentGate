from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agentgate.approvals import (
    APPROVAL_DB_SCHEMA_VERSION,
    ApprovalConflict,
    ApprovalNotExecutable,
    ApprovalQueue,
    ApprovalStatus,
    ExecutionStatus,
)
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.tools import ExecutionAuthorization, ToolExecutor
from agentgate.workspace import WorkspaceBoundary


def approval_request(tmp_path: Path, **overrides: object) -> ToolRequest:
    payload: dict[str, object] = {
        "request_id": "req_write_private_note",
        "actor": "demo-agent",
        "tool": "file.write",
        "action": "write",
        "resource": "examples/workspace/private/draft_note.txt",
        "input": {"content": "approved synthetic content"},
        "metadata": {"scenario": "write_requires_approval"},
    }
    payload.update(overrides)
    return ToolRequest.model_validate(payload)


def approval_decision(request: ToolRequest) -> Decision:
    return Decision(
        request_id=request.request_id,
        status=DecisionStatus.REQUIRE_APPROVAL,
        risk=RiskLevel.MEDIUM,
        reason="File write operations require human approval.",
        matched_rule="file_write_requires_approval",
    )


def deny_decision(request: ToolRequest) -> Decision:
    return Decision(
        request_id=request.request_id,
        status=DecisionStatus.DENY,
        risk=RiskLevel.CRITICAL,
        reason="Denied.",
        matched_rule="delete_denied",
    )


def queue(tmp_path: Path) -> ApprovalQueue:
    return ApprovalQueue(tmp_path / "approvals.sqlite")


def workspace(tmp_path: Path) -> WorkspaceBoundary:
    public = tmp_path / "examples" / "workspace" / "public"
    private = tmp_path / "examples" / "workspace" / "private"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    return WorkspaceBoundary(
        base_dir=tmp_path,
        public_root=public,
        private_root=private,
    )


def test_create_pending_approval_preserves_request_payload(tmp_path: Path) -> None:
    request = approval_request(tmp_path)

    record = queue(tmp_path).create_pending(request, approval_decision(request))

    assert record.status == ApprovalStatus.PENDING
    assert record.request_id == request.request_id
    assert record.request.model_dump(mode="json") == request.model_dump(mode="json")
    assert record.decision.approval_id == record.approval_id


def test_create_pending_rejects_non_approval_decision(tmp_path: Path) -> None:
    request = approval_request(tmp_path)

    with pytest.raises(ApprovalConflict):
        queue(tmp_path).create_pending(request, deny_decision(request))


def test_duplicate_pending_for_same_request_is_idempotent(tmp_path: Path) -> None:
    request = approval_request(tmp_path)
    approvals = queue(tmp_path)

    first = approvals.create_pending(request, approval_decision(request))
    second = approvals.create_pending(request, approval_decision(request))

    assert second.approval_id == first.approval_id
    assert len(approvals.list()) == 1


def test_duplicate_request_id_with_different_payload_is_rejected(
    tmp_path: Path,
) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    changed = approval_request(tmp_path, input={"content": "changed"})

    approvals.create_pending(request, approval_decision(request))

    with pytest.raises(ApprovalConflict):
        approvals.create_pending(changed, approval_decision(changed))


def test_list_filters_approval_records(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    write_request = approval_request(tmp_path)
    append_request = approval_request(
        tmp_path,
        request_id="req_append_private_note",
        actor="review-agent",
        tool="file.append",
        action="append",
    )
    write_record = approvals.create_pending(
        write_request,
        approval_decision(write_request),
    )
    approvals.create_pending(append_request, approval_decision(append_request))
    approvals.approve(
        write_record.approval_id,
        approver="human-reviewer",
        expected_request_id=write_request.request_id,
    )
    approvals.claim_for_execution(write_record.approval_id)

    assert [
        record.request_id
        for record in approvals.list(request_id=append_request.request_id)
    ] == [append_request.request_id]
    assert [record.request_id for record in approvals.list(actor="review-agent")] == [
        append_request.request_id
    ]
    assert [record.request_id for record in approvals.list(tool="file.append")] == [
        append_request.request_id
    ]
    assert [
        record.request_id
        for record in approvals.list(execution_status=ExecutionStatus.IN_PROGRESS)
    ] == [write_request.request_id]


def test_approval_persists_after_reopening_database(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    request = approval_request(tmp_path)
    created = ApprovalQueue(db_path).create_pending(request, approval_decision(request))

    loaded = ApprovalQueue(db_path).get(created.approval_id)

    assert loaded.approval_id == created.approval_id
    assert loaded.request.model_dump(mode="json") == request.model_dump(mode="json")


def test_new_approval_database_records_schema_version(tmp_path: Path) -> None:
    approvals = queue(tmp_path)

    assert approvals.schema_version() == APPROVAL_DB_SCHEMA_VERSION


def test_existing_approval_database_adds_edit_history_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "approvals.sqlite"
    approval_id = "appr_legacy"
    request = approval_request(tmp_path)
    decision = approval_decision(request).model_copy(
        update={"approval_id": approval_id}
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE approvals (
                approval_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decided_by TEXT,
                decision_reason TEXT,
                execution_status TEXT NOT NULL,
                executed_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO approvals (
                approval_id,
                request_id,
                status,
                request_json,
                decision_json,
                created_at,
                decided_at,
                decided_by,
                decision_reason,
                execution_status,
                executed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                request.request_id,
                ApprovalStatus.PENDING.value,
                request.model_dump_json(),
                decision.model_dump_json(),
                "2026-05-16T00:00:00+00:00",
                None,
                None,
                None,
                ExecutionStatus.NOT_EXECUTED.value,
                None,
            ),
        )

    approvals = ApprovalQueue(db_path)
    edited = approval_request(tmp_path, input={"content": "edited after migration"})

    assert approvals.schema_version() == APPROVAL_DB_SCHEMA_VERSION
    assert approvals.get(approval_id).request_id == request.request_id
    assert approvals.list_edits(approval_id) == []

    approvals.edit_pending(
        approval_id,
        edited,
        approval_decision(edited),
        editor="human-reviewer",
        expected_request_id=request.request_id,
    )

    edits = approvals.list_edits(approval_id)

    assert len(edits) == 1
    assert edits[0].previous_request.input == {"content": "approved synthetic content"}
    assert edits[0].edited_request.input == {"content": "edited after migration"}


def test_approve_and_reject_are_one_way_state_transitions(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))

    approved = approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        reason="Looks correct.",
        expected_request_id=request.request_id,
    )

    assert approved.status == ApprovalStatus.APPROVED
    assert approved.decided_by == "human-reviewer"
    with pytest.raises(ApprovalConflict):
        approvals.reject(
            record.approval_id,
            approver="human-reviewer",
            expected_request_id=request.request_id,
        )


def test_reject_cannot_later_be_approved(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))

    rejected = approvals.reject(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )

    assert rejected.status == ApprovalStatus.REJECTED
    with pytest.raises(ApprovalConflict):
        approvals.approve(
            record.approval_id,
            approver="human-reviewer",
            expected_request_id=request.request_id,
        )


def test_request_id_guard_blocks_mismatched_approval(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))

    with pytest.raises(ApprovalConflict):
        approvals.approve(
            record.approval_id,
            approver="human-reviewer",
            expected_request_id="req_other",
        )


def test_edit_pending_replaces_request_payload(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    edited = approval_request(tmp_path, input={"content": "edited synthetic content"})

    updated = approvals.edit_pending(
        record.approval_id,
        edited,
        approval_decision(edited),
        editor="human-reviewer",
        reason="Narrowed the approved content.",
        expected_request_id=request.request_id,
    )

    assert updated.status == ApprovalStatus.PENDING
    assert updated.request.input == {"content": "edited synthetic content"}
    assert updated.decision.approval_id == record.approval_id


def test_edit_pending_records_payload_history(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    edited = approval_request(tmp_path, input={"content": "edited synthetic content"})

    approvals.edit_pending(
        record.approval_id,
        edited,
        approval_decision(edited),
        editor="human-reviewer",
        reason="Narrowed the approved content.",
        expected_request_id=request.request_id,
    )

    edits = approvals.list_edits(record.approval_id)

    assert len(edits) == 1
    assert edits[0].approval_id == record.approval_id
    assert edits[0].request_id == request.request_id
    assert edits[0].previous_request.input == {"content": "approved synthetic content"}
    assert edits[0].edited_request.input == {"content": "edited synthetic content"}
    assert edits[0].previous_decision.approval_id == record.approval_id
    assert edits[0].edited_decision.approval_id == record.approval_id
    assert edits[0].edited_by == "human-reviewer"
    assert edits[0].edit_reason == "Narrowed the approved content."


def test_edit_pending_records_each_payload_revision(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    first_edit = approval_request(tmp_path, input={"content": "first edit"})
    second_edit = approval_request(tmp_path, input={"content": "second edit"})

    approvals.edit_pending(
        record.approval_id,
        first_edit,
        approval_decision(first_edit),
        editor="human-reviewer",
        expected_request_id=request.request_id,
    )
    approvals.edit_pending(
        record.approval_id,
        second_edit,
        approval_decision(second_edit),
        editor="human-reviewer",
        expected_request_id=request.request_id,
    )

    edits = approvals.list_edits(record.approval_id)

    assert len(edits) == 2
    assert edits[0].previous_request.input == {"content": "approved synthetic content"}
    assert edits[0].edited_request.input == {"content": "first edit"}
    assert edits[1].previous_request.input == {"content": "first edit"}
    assert edits[1].edited_request.input == {"content": "second edit"}


def test_edit_pending_rejects_changed_request_id(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    edited = approval_request(
        tmp_path,
        request_id="req_different",
        input={"content": "edited synthetic content"},
    )

    with pytest.raises(ApprovalConflict):
        approvals.edit_pending(
            record.approval_id,
            edited,
            approval_decision(edited),
            editor="human-reviewer",
            expected_request_id=request.request_id,
        )


def test_edit_pending_rejects_decision_for_different_request_id(
    tmp_path: Path,
) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    edited = approval_request(tmp_path, input={"content": "edited synthetic content"})
    other_request = approval_request(tmp_path, request_id="req_other")

    with pytest.raises(ApprovalConflict):
        approvals.edit_pending(
            record.approval_id,
            edited,
            approval_decision(other_request),
            editor="human-reviewer",
            expected_request_id=request.request_id,
        )


def test_edit_pending_rejects_non_approval_decision(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))

    with pytest.raises(ApprovalConflict):
        approvals.edit_pending(
            record.approval_id,
            request,
            deny_decision(request),
            editor="human-reviewer",
            expected_request_id=request.request_id,
        )


def test_decided_approval_cannot_be_edited(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )
    edited = approval_request(tmp_path, input={"content": "edited synthetic content"})

    with pytest.raises(ApprovalConflict):
        approvals.edit_pending(
            record.approval_id,
            edited,
            approval_decision(edited),
            editor="human-reviewer",
            expected_request_id=request.request_id,
        )


def test_executor_uses_edited_approved_request_payload(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    edited = approval_request(tmp_path, input={"content": "edited synthetic content"})
    approvals.edit_pending(
        record.approval_id,
        edited,
        approval_decision(edited),
        editor="human-reviewer",
        expected_request_id=request.request_id,
    )
    approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )

    claimed = approvals.claim_for_execution(record.approval_id)
    authorization = ExecutionAuthorization.from_approval_claim(claimed)
    result = ToolExecutor(workspace(tmp_path)).execute(
        claimed.request,
        authorization=authorization,
    )
    target = tmp_path / "examples" / "workspace" / "private" / "draft_note.txt"

    assert result.result_status == "completed"
    assert target.read_text(encoding="utf-8") == "edited synthetic content"


def test_only_approved_requests_are_executable_once(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))

    with pytest.raises(ApprovalNotExecutable):
        approvals.get_executable_request(record.approval_id)

    approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )
    claimed = approvals.claim_for_execution(record.approval_id)
    assert claimed.request.request_id == request.request_id
    assert claimed.execution_status == ExecutionStatus.IN_PROGRESS
    with pytest.raises(ApprovalNotExecutable):
        approvals.claim_for_execution(record.approval_id)

    executed = approvals.mark_executed(
        record.approval_id,
        result_status=ExecutionStatus.COMPLETED,
    )
    assert executed.execution_status == ExecutionStatus.COMPLETED
    with pytest.raises(ApprovalNotExecutable):
        approvals.get_executable_request(record.approval_id)


def test_mark_executed_requires_claimed_approval(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )

    with pytest.raises(ApprovalNotExecutable):
        approvals.mark_executed(
            record.approval_id,
            result_status=ExecutionStatus.COMPLETED,
        )


def test_two_queue_instances_cannot_claim_same_approval(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    first_queue = ApprovalQueue(db_path)
    second_queue = ApprovalQueue(db_path)
    request = approval_request(tmp_path)
    record = first_queue.create_pending(request, approval_decision(request))
    first_queue.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )

    claimed = first_queue.claim_for_execution(record.approval_id)

    assert claimed.execution_status == ExecutionStatus.IN_PROGRESS
    with pytest.raises(ApprovalNotExecutable):
        second_queue.claim_for_execution(record.approval_id)
    assert second_queue.get(record.approval_id).execution_status == (
        ExecutionStatus.IN_PROGRESS
    )


def test_executor_uses_stored_approved_request_payload(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )

    claimed = approvals.claim_for_execution(record.approval_id)
    authorization = ExecutionAuthorization.from_approval_claim(claimed)
    result = ToolExecutor(workspace(tmp_path)).execute(
        claimed.request,
        authorization=authorization,
    )
    target = tmp_path / "examples" / "workspace" / "private" / "draft_note.txt"

    assert result.result_status == "completed"
    assert target.read_text(encoding="utf-8") == "approved synthetic content"


def test_executor_denies_direct_unauthorized_execution(tmp_path: Path) -> None:
    request = approval_request(tmp_path)
    target = tmp_path / "examples" / "workspace" / "private" / "draft_note.txt"

    result = ToolExecutor(workspace(tmp_path)).execute(request)

    assert result.result_status == "denied"
    assert target.exists() is False


def test_executor_denies_mismatched_authorization_payload(tmp_path: Path) -> None:
    approvals = queue(tmp_path)
    request = approval_request(tmp_path)
    record = approvals.create_pending(request, approval_decision(request))
    approvals.approve(
        record.approval_id,
        approver="human-reviewer",
        expected_request_id=request.request_id,
    )
    claimed = approvals.claim_for_execution(record.approval_id)
    authorization = ExecutionAuthorization.from_approval_claim(claimed)
    changed_request = request.model_copy(update={"input": {"content": "changed"}})

    result = ToolExecutor(workspace(tmp_path)).execute(
        changed_request,
        authorization=authorization,
    )

    assert result.result_status == "denied"
    assert result.message == "Execution authorization payload does not match request."
