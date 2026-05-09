from __future__ import annotations

from pathlib import Path

from agentgate.policy import PolicyEngine
from agentgate.registry import ToolDefinition, ToolRegistry, WRITE_TOOLS
from agentgate.schemas import DecisionStatus, RiskLevel
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
