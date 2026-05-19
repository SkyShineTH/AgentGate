from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentgate.approvals import ApprovalRecord, ApprovalStatus, ExecutionStatus
from agentgate.registry import ToolRegistry
from agentgate.schemas import Decision, DecisionStatus, ToolRequest
from agentgate.workspace import WorkspaceBoundary


def request_fingerprint(request: ToolRequest) -> str:
    payload = request.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExecutionAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["policy_allow", "approval_claim"]
    request_id: str
    request_fingerprint: str
    decision_status: DecisionStatus
    approval_id: str | None = None

    @classmethod
    def from_policy_decision(
        cls,
        request: ToolRequest,
        decision: Decision,
    ) -> "ExecutionAuthorization":
        if decision.request_id != request.request_id:
            raise ValueError("Decision request_id must match request.")
        if decision.status != DecisionStatus.ALLOW:
            raise ValueError("Only allow decisions can authorize direct execution.")
        return cls(
            source="policy_allow",
            request_id=request.request_id,
            request_fingerprint=request_fingerprint(request),
            decision_status=decision.status,
        )

    @classmethod
    def from_approval_claim(
        cls,
        record: ApprovalRecord,
    ) -> "ExecutionAuthorization":
        if record.status != ApprovalStatus.APPROVED:
            raise ValueError("Only approved records can authorize execution.")
        if record.execution_status != ExecutionStatus.IN_PROGRESS:
            raise ValueError("Approval must be claimed before execution.")
        if record.decision.status != DecisionStatus.REQUIRE_APPROVAL:
            raise ValueError("Approval decision must be require_approval.")
        if record.decision.approval_id != record.approval_id:
            raise ValueError("Approval decision must match approval_id.")
        return cls(
            source="approval_claim",
            request_id=record.request_id,
            request_fingerprint=request_fingerprint(record.request),
            decision_status=record.decision.status,
            approval_id=record.approval_id,
        )

    def failure_reason(self, request: ToolRequest) -> str | None:
        if self.request_id != request.request_id:
            return "Execution authorization request_id does not match request."
        if self.request_fingerprint != request_fingerprint(request):
            return "Execution authorization payload does not match request."
        if (
            self.source == "policy_allow"
            and self.decision_status != DecisionStatus.ALLOW
        ):
            return "Direct execution requires an allow decision."
        if (
            self.source == "approval_claim"
            and self.decision_status != DecisionStatus.REQUIRE_APPROVAL
        ):
            return "Approval execution requires a require_approval decision."
        return None


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    result_status: str
    tool: str
    action: str
    resource: str
    message: str
    bytes_processed: int | None = None


class ToolExecutor:
    def __init__(
        self,
        workspace: WorkspaceBoundary | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.workspace = workspace or WorkspaceBoundary.default()
        self.registry = registry or ToolRegistry.default()

    @classmethod
    def default(cls) -> "ToolExecutor":
        return cls()

    def execute(
        self,
        request: ToolRequest,
        *,
        authorization: ExecutionAuthorization | None = None,
    ) -> ExecutionResult:
        if authorization is None:
            return self._result(
                request,
                result_status="denied",
                message=(
                    "Tool execution requires an allow decision or approved request."
                ),
            )
        failure_reason = authorization.failure_reason(request)
        if failure_reason is not None:
            return self._result(
                request,
                result_status="denied",
                message=failure_reason,
            )

        tool = self.registry.get(request.tool)
        if tool is None or not tool.supports_action(request.action):
            return self._result(
                request,
                result_status="denied",
                message="No executor is registered for this tool.",
            )

        if request.tool == "shell.execute":
            return self._result(
                request,
                result_status="denied",
                message="Shell execution is not implemented by AgentGate.",
            )

        if request.tool == "file.delete":
            return self._result(
                request,
                result_status="denied",
                message="File delete execution is denied by default.",
            )

        boundary = self.workspace.resolve(request.resource)
        if not boundary.allowed or boundary.normalized_path is None:
            return self._result(
                request,
                result_status="denied",
                message=boundary.reason,
            )

        if request.tool == "file.read":
            return self._read(request, boundary.normalized_path)

        if tool.has_side_effects and tool.executable:
            return self._write(request, boundary.normalized_path)

        return self._result(
            request,
            result_status="denied",
            message="No executor is registered for this tool.",
        )

    def _read(self, request: ToolRequest, path: Path) -> ExecutionResult:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return self._result(
                request,
                result_status="failed",
                message=f"File read failed: {exc}",
            )
        return self._result(
            request,
            result_status="completed",
            message="File read completed. Content is not included in the result.",
            bytes_processed=len(content.encode("utf-8")),
        )

    def _write(self, request: ToolRequest, path: Path) -> ExecutionResult:
        content = request.input.get("content")
        if not isinstance(content, str):
            return self._result(
                request,
                result_status="failed",
                message="File write input must include string field 'content'.",
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if request.tool == "file.append":
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(content)
            else:
                path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return self._result(
                request,
                result_status="failed",
                message=f"File write failed: {exc}",
            )

        return self._result(
            request,
            result_status="completed",
            message="File write completed.",
            bytes_processed=len(content.encode("utf-8")),
        )

    @staticmethod
    def _result(
        request: ToolRequest,
        *,
        result_status: str,
        message: str,
        bytes_processed: int | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            request_id=request.request_id,
            result_status=result_status,
            tool=request.tool,
            action=request.action,
            resource=request.resource,
            message=message,
            bytes_processed=bytes_processed,
        )
