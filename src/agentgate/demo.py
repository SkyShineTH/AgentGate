from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agentgate.approvals import ApprovalQueue, ExecutionStatus
from agentgate.audit import AuditLog
from agentgate.policy import PolicyEngine
from agentgate.schemas import DecisionStatus, ToolRequest
from agentgate.tools import ExecutionAuthorization, ToolExecutor
from agentgate.workspace import WorkspaceBoundary

REPO_ROOT = Path(__file__).resolve().parents[2]
PERSONALOPS_ROOT = REPO_ROOT / "examples" / "personalops"
PERSONALOPS_REQUESTS = [
    "read_public_job_plan.json",
    "append_private_job_tracker_requires_approval.json",
    "delete_private_job_tracker_denied.json",
    "shell_command_denied.json",
]


class DemoStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    request_id: str
    status: str
    risk: str
    matched_rule: str
    approval_id: str | None = None
    approval_status: str | None = None
    execution_status: str | None = None


class PersonalOpsDemoReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_dir: str
    approval_db: str
    audit_log: str
    steps: list[DemoStepResult]


def run_personalops_demo(
    *,
    state_dir: Path = Path(".agentgate") / "personalops-demo",
    reset: bool = True,
    auto_approve: bool = True,
) -> PersonalOpsDemoReport:
    """Run a synthetic PersonalOps workflow through the policy gateway."""
    state_dir = state_dir.resolve(strict=False)
    if reset and state_dir.exists():
        shutil.rmtree(state_dir)

    workspace_root = _seed_workspace(state_dir)
    approval_db = state_dir / "approvals.sqlite"
    audit_log_path = state_dir / "audit.jsonl"

    workspace = WorkspaceBoundary(
        base_dir=state_dir,
        public_root=workspace_root / "public",
        private_root=workspace_root / "private",
    )
    policy = PolicyEngine(workspace)
    executor = ToolExecutor(workspace)
    queue = ApprovalQueue(approval_db)
    audit = AuditLog(audit_log_path)

    steps = []
    for request_file in PERSONALOPS_REQUESTS:
        request = _load_request(PERSONALOPS_ROOT / "requests" / request_file)
        decision = policy.evaluate(request)
        audit.record(
            event_type="policy_decision",
            request=request,
            decision=decision,
            payload={"scenario": request.metadata.get("scenario")},
        )

        step = DemoStepResult(
            name=request.metadata.get("scenario", request_file),
            request_id=request.request_id,
            status=decision.status.value,
            risk=decision.risk.value,
            matched_rule=decision.matched_rule,
        )

        if decision.status == DecisionStatus.ALLOW:
            authorization = ExecutionAuthorization.from_policy_decision(
                request,
                decision,
            )
            result = executor.execute(request, authorization=authorization)
            audit.record(
                event_type="executed",
                request=request,
                decision=decision,
                result_status=result.result_status,
                payload={"result": result.model_dump(mode="json")},
            )
            step.execution_status = result.result_status

        if decision.status == DecisionStatus.REQUIRE_APPROVAL:
            pending = queue.create_pending_result(request, decision)
            record = pending.record
            audit.record(
                event_type=(
                    "approval_created" if pending.created else "approval_existing"
                ),
                request=record.request,
                decision=record.decision,
                approval_id=record.approval_id,
            )
            step.approval_id = record.approval_id
            step.approval_status = record.status.value

            if auto_approve:
                record = queue.approve(
                    record.approval_id,
                    approver="demo-human",
                    expected_request_id=record.request_id,
                    reason="Synthetic demo approval.",
                )
                audit.record(
                    event_type="approval_decided",
                    request=record.request,
                    decision=record.decision,
                    approval_id=record.approval_id,
                    payload={
                        "approval_status": record.status.value,
                        "decided_by": record.decided_by,
                    },
                )
                claimed = queue.claim_for_execution(record.approval_id)
                authorization = ExecutionAuthorization.from_approval_claim(claimed)
                result = executor.execute(
                    claimed.request,
                    authorization=authorization,
                )
                executed_status = ExecutionStatus(result.result_status)
                queue.mark_executed(
                    record.approval_id,
                    result_status=executed_status,
                )
                audit.record(
                    event_type="executed",
                    request=claimed.request,
                    decision=record.decision,
                    approval_id=record.approval_id,
                    result_status=result.result_status,
                    payload={"result": result.model_dump(mode="json")},
                )
                step.approval_status = record.status.value
                step.execution_status = result.result_status

        steps.append(step)

    return PersonalOpsDemoReport(
        state_dir=str(state_dir),
        approval_db=str(approval_db),
        audit_log=str(audit_log_path),
        steps=steps,
    )


def _seed_workspace(state_dir: Path) -> Path:
    source = PERSONALOPS_ROOT / "workspace"
    target = state_dir / "examples" / "workspace"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _load_request(path: Path) -> ToolRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ToolRequest.model_validate(payload)
