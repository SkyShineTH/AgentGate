from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agentgate.policy_config import PolicyConfig
from agentgate.registry import ToolRegistry
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.secrets import contains_likely_secret
from agentgate.workspace import WorkspaceBoundary, WorkspaceKind


class PolicyEngine:
    def __init__(
        self,
        workspace: WorkspaceBoundary | None = None,
        registry: ToolRegistry | None = None,
        config: PolicyConfig | None = None,
    ) -> None:
        self.workspace = workspace or WorkspaceBoundary.default()
        self.registry = registry or ToolRegistry.default()
        self.config = config or PolicyConfig()

    @classmethod
    def default(cls) -> "PolicyEngine":
        return cls()

    def evaluate(self, request_data: ToolRequest | Mapping[str, Any]) -> Decision:
        request = self._parse_request(request_data)
        if isinstance(request, Decision):
            return request

        if contains_likely_secret(request.input):
            return self._decision(
                request,
                status=DecisionStatus.DENY,
                risk=RiskLevel.CRITICAL,
                reason="Request input contains a likely secret.",
                matched_rule="secret_input_denied",
            )

        tool = self.registry.get(request.tool)
        if tool is None:
            return self._decision(
                request,
                status=self.config.unknown_tool,
                risk=RiskLevel.HIGH,
                reason="Unknown tools are denied by default.",
                matched_rule="unknown_tool_denied",
            )

        if not tool.supports_action(request.action):
            return self._decision(
                request,
                status=self.config.unknown_action,
                risk=RiskLevel.HIGH,
                reason="Unknown actions are denied by default.",
                matched_rule="unknown_action_denied",
            )

        if request.tool == "shell.execute":
            return self._decision(
                request,
                status=self.config.shell_execute,
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
                status=self.config.file_delete,
                risk=RiskLevel.CRITICAL,
                reason="File delete operations are denied by default.",
                matched_rule="delete_denied",
            )

        if tool.has_side_effects:
            if self.config.file_write == DecisionStatus.DENY:
                return self._decision(
                    request,
                    status=DecisionStatus.DENY,
                    risk=RiskLevel.HIGH,
                    reason="File write operations are denied by policy profile.",
                    matched_rule="file_write_denied_by_policy",
                )
            return self._decision(
                request,
                status=self.config.file_write,
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
                if self.config.private_read == DecisionStatus.DENY:
                    return self._decision(
                        request,
                        status=DecisionStatus.DENY,
                        risk=RiskLevel.MEDIUM,
                        reason="Private workspace reads are denied by policy profile.",
                        matched_rule="private_read_denied_by_policy",
                    )
                return self._decision(
                    request,
                    status=self.config.private_read,
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
