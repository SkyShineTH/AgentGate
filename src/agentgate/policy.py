from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.workspace import WorkspaceBoundary, WorkspaceKind


SUPPORTED_ACTIONS: dict[str, set[str]] = {
    "file.read": {"read"},
    "file.write": {"write", "create"},
    "file.append": {"append"},
    "file.update": {"update"},
    "file.delete": {"delete"},
    "shell.execute": {"execute"},
}

WRITE_TOOLS = {"file.write", "file.append", "file.update"}

SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|auth[_-]?token|bearer|client[_-]?secret|"
    r"password|passwd|private[_-]?key|secret)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9_-]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,})"
)


class PolicyEngine:
    def __init__(self, workspace: WorkspaceBoundary | None = None) -> None:
        self.workspace = workspace or WorkspaceBoundary.default()

    @classmethod
    def default(cls) -> "PolicyEngine":
        return cls()

    def evaluate(self, request_data: ToolRequest | Mapping[str, Any]) -> Decision:
        request = self._parse_request(request_data)
        if isinstance(request, Decision):
            return request

        if self._contains_likely_secret(request.input):
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=RiskLevel.CRITICAL,
                reason="Request input contains a likely secret.",
                matched_rule="secret_input_denied",
            )

        if request.tool not in SUPPORTED_ACTIONS:
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=RiskLevel.HIGH,
                reason="Unknown tools are denied by default.",
                matched_rule="unknown_tool_denied",
            )

        if request.action not in SUPPORTED_ACTIONS[request.tool]:
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=RiskLevel.HIGH,
                reason="Unknown actions are denied by default.",
                matched_rule="unknown_action_denied",
            )

        if request.tool == "shell.execute":
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=RiskLevel.HIGH,
                reason="Shell execution is denied by default.",
                matched_rule="shell_denied_by_default",
            )

        boundary = self.workspace.resolve(request.resource)
        if not boundary.allowed:
            rule = boundary.matched_rule or "path_outside_workspace_denied"
            risk = (
                RiskLevel.HIGH
                if rule == "path_traversal_denied"
                else RiskLevel.CRITICAL
            )
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=risk,
                reason=boundary.reason,
                matched_rule=rule,
            )

        if request.tool == "file.delete":
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=RiskLevel.CRITICAL,
                reason="File delete operations are denied by default.",
                matched_rule="delete_denied",
            )

        if request.tool in WRITE_TOOLS:
            return self._decision(
                request,
                status=DecisionStatus.REQUIRE_APPROVAL,
                risk=RiskLevel.MEDIUM,
                reason="File write operations require human approval.",
                matched_rule="file_write_requires_approval",
            )

        if request.tool == "file.read":
            if boundary.workspace_kind == WorkspaceKind.PUBLIC:
                return self._decision(
                    request,
                    status=DecisionStatus.ALLOW,
                    risk=RiskLevel.LOW,
                    reason="Public workspace reads are allowed.",
                    matched_rule="public_read_allowed",
                )
            if boundary.workspace_kind == WorkspaceKind.PRIVATE:
                return self._decision(
                    request,
                    status=DecisionStatus.REQUIRE_APPROVAL,
                    risk=RiskLevel.MEDIUM,
                    reason="Private workspace reads require human approval.",
                    matched_rule="private_read_requires_approval",
                )

        return self._decision(
            request,
            status=DecisionStatus.DENY,
            risk=RiskLevel.HIGH,
            reason="No policy rule allowed this request.",
            matched_rule="default_deny",
        )

    def _parse_request(
        self, request_data: ToolRequest | Mapping[str, Any]
    ) -> ToolRequest | Decision:
        if isinstance(request_data, ToolRequest):
            return request_data

        request_id = self._request_id_from_payload(request_data)
        try:
            return ToolRequest.model_validate(request_data)
        except ValidationError:
            return Decision(
                request_id=request_id,
                status=DecisionStatus.DENY,
                risk=RiskLevel.HIGH,
                reason="Malformed requests are denied by default.",
                matched_rule="malformed_request_denied",
            )

    @staticmethod
    def _request_id_from_payload(request_data: Mapping[str, Any]) -> str:
        request_id = request_data.get("request_id")
        if isinstance(request_id, str) and request_id.strip():
            return request_id.strip()
        return "req_malformed"

    @staticmethod
    def _decision(
        request: ToolRequest,
        *,
        status: DecisionStatus,
        risk: RiskLevel,
        reason: str,
        matched_rule: str,
    ) -> Decision:
        return Decision(
            request_id=request.request_id,
            status=status,
            risk=risk,
            reason=reason,
            matched_rule=matched_rule,
        )

    @classmethod
    def _contains_likely_secret(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if isinstance(key, str) and SECRET_KEY_RE.search(key):
                    return True
                if cls._contains_likely_secret(nested):
                    return True
            return False

        if isinstance(value, list | tuple | set):
            return any(cls._contains_likely_secret(item) for item in value)

        if isinstance(value, str):
            return bool(SECRET_VALUE_RE.search(value))

        return False

