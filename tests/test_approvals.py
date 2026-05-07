from __future__ import annotations

from pathlib import Path

import pytest

from agentgate.approvals import (
    ApprovalConflict,
    ApprovalNotExecutable,
    ApprovalQueue,
    ApprovalStatus,
    ExecutionStatus,
)
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.tools import ToolExecutor
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


def test_approval_persists_after_reopening_database(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    request = approval_request(tmp_path)
    created = ApprovalQueue(db_path).create_pending(request, approval_decision(request))

    loaded = ApprovalQueue(db_path).get(created.approval_id)

    assert loaded.approval_id == created.approval_id
    assert loaded.request.model_dump(mode="json") == request.model_dump(mode="json")


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
    result = ToolExecutor(workspace(tmp_path)).execute(
        claimed.request,
        authorized=True,
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
