from __future__ import annotations

from pathlib import Path

from agentgate.approvals import ApprovalRecord, ApprovalStatus, ExecutionStatus
from agentgate.policy import PolicyEngine
from agentgate.registry import WRITE_TOOLS, ToolDefinition, ToolRegistry
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.tools import ExecutionAuthorization, ToolExecutor
from agentgate.workspace import WorkspaceBoundary


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


def request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": "req_registry_test",
        "actor": "demo-agent",
        "tool": "file.read",
        "action": "read",
        "resource": "examples/workspace/public/note.txt",
        "input": {},
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def approval_authorization(request: ToolRequest) -> ExecutionAuthorization:
    record = ApprovalRecord(
        approval_id="appr_registry_test",
        request_id=request.request_id,
        status=ApprovalStatus.APPROVED,
        request=request,
        decision=Decision(
            request_id=request.request_id,
            status=DecisionStatus.REQUIRE_APPROVAL,
            risk=RiskLevel.MEDIUM,
            reason="Approved in registry executor test.",
            matched_rule="file_write_requires_approval",
            approval_id="appr_registry_test",
        ),
        execution_status=ExecutionStatus.IN_PROGRESS,
    )
    return ExecutionAuthorization.from_approval_claim(record)


def test_default_registry_lists_known_file_and_shell_tools() -> None:
    registry = ToolRegistry.default()

    assert registry.supports_action("file.read", "read") is True
    assert registry.supports_action("file.write", "create") is True
    assert registry.supports_action("shell.execute", "execute") is True
    assert registry.get("browser.open") is None
    assert WRITE_TOOLS == frozenset({"file.write", "file.append", "file.update"})


def test_policy_uses_injected_registry_for_unknown_tools(tmp_path: Path) -> None:
    empty_registry = ToolRegistry([])
    decision = PolicyEngine(workspace(tmp_path), registry=empty_registry).evaluate(
        request()
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.risk == RiskLevel.HIGH
    assert decision.matched_rule == "unknown_tool_denied"


def test_policy_uses_registry_supported_actions(tmp_path: Path) -> None:
    registry = ToolRegistry(
        [
            ToolDefinition(
                name="file.read",
                actions=frozenset({"inspect"}),
                default_risk=RiskLevel.LOW,
            )
        ]
    )
    decision = PolicyEngine(workspace(tmp_path), registry=registry).evaluate(
        request(action="read")
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "unknown_action_denied"


def test_policy_uses_injected_registry_for_side_effects(tmp_path: Path) -> None:
    registry = ToolRegistry(
        [
            ToolDefinition(
                name="file.write",
                actions=frozenset({"write"}),
                default_risk=RiskLevel.LOW,
                has_side_effects=False,
            )
        ]
    )
    decision = PolicyEngine(workspace(tmp_path), registry=registry).evaluate(
        request(
            tool="file.write",
            action="write",
            resource="examples/workspace/private/note.txt",
            input={"content": "synthetic note"},
        )
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "default_deny"


def test_executor_uses_injected_registry_for_side_effects(tmp_path: Path) -> None:
    registry = ToolRegistry(
        [
            ToolDefinition(
                name="file.write",
                actions=frozenset({"write"}),
                default_risk=RiskLevel.LOW,
                has_side_effects=False,
                executable=True,
            )
        ]
    )
    executor = ToolExecutor(workspace(tmp_path), registry=registry)
    tool_request = ToolRequest.model_validate(
        request(
            tool="file.write",
            action="write",
            resource="examples/workspace/private/note.txt",
            input={"content": "synthetic note"},
        )
    )

    result = executor.execute(
        tool_request,
        authorization=approval_authorization(tool_request),
    )

    assert result.result_status == "denied"
    assert result.message == "No executor is registered for this tool."
    assert not (tmp_path / "examples" / "workspace" / "private" / "note.txt").exists()


def test_executor_allows_custom_registered_side_effect_tool(tmp_path: Path) -> None:
    registry = ToolRegistry(
        [
            ToolDefinition(
                name="file.redact",
                actions=frozenset({"write"}),
                default_risk=RiskLevel.MEDIUM,
                has_side_effects=True,
                executable=True,
            )
        ]
    )
    executor = ToolExecutor(workspace(tmp_path), registry=registry)
    tool_request = ToolRequest.model_validate(
        request(
            tool="file.redact",
            action="write",
            resource="examples/workspace/private/redacted.txt",
            input={"content": "redacted synthetic note"},
        )
    )

    result = executor.execute(
        tool_request,
        authorization=approval_authorization(tool_request),
    )

    assert result.result_status == "completed"
    assert (tmp_path / "examples" / "workspace" / "private" / "redacted.txt").read_text(
        encoding="utf-8"
    ) == "redacted synthetic note"
