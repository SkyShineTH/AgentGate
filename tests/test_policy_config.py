from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentgate.config import AgentGateConfig, AgentGateConfigError
from agentgate.policy import PolicyEngine
from agentgate.policy_config import PolicyConfig, PolicyConfigError
from agentgate.schemas import DecisionStatus
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
        "request_id": "req_config_test",
        "actor": "demo-agent",
        "tool": "file.read",
        "action": "read",
        "resource": "examples/workspace/private/note.txt",
        "input": {},
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def test_policy_config_can_deny_private_reads(tmp_path: Path) -> None:
    config = PolicyConfig(private_read=DecisionStatus.DENY)

    decision = PolicyEngine(workspace(tmp_path), config=config).evaluate(request())

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "private_read_denied_by_policy"


def test_policy_config_can_deny_file_writes(tmp_path: Path) -> None:
    config = PolicyConfig(file_write=DecisionStatus.DENY)

    decision = PolicyEngine(workspace(tmp_path), config=config).evaluate(
        request(
            tool="file.write",
            action="write",
            input={"content": "synthetic note"},
        )
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "file_write_denied_by_policy"


def test_policy_config_loads_from_json_file(tmp_path: Path) -> None:
    config_path = tmp_path / "policy.json"
    config_path.write_text(
        json.dumps({"private_read": "deny", "file_write": "require_approval"}),
        encoding="utf-8",
    )

    config = PolicyConfig.from_json_file(config_path)

    assert config.private_read == DecisionStatus.DENY
    assert config.file_write == DecisionStatus.REQUIRE_APPROVAL


def test_policy_config_rejects_unsafe_status_values() -> None:
    with pytest.raises(ValidationError):
        PolicyConfig(private_read=DecisionStatus.ALLOW)
    with pytest.raises(ValidationError):
        PolicyConfig(shell_execute=DecisionStatus.REQUIRE_APPROVAL)


def test_policy_config_rejects_malformed_json(tmp_path: Path) -> None:
    config_path = tmp_path / "policy.json"
    config_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(PolicyConfigError):
        PolicyConfig.from_json_file(config_path)


def test_agentgate_config_loads_workspace_and_policy_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "agentgate.toml"
    config_path.write_text(
        """
[workspace]
base_dir = "workspace"
public_root = "public"
private_root = "private"

[policy]
private_read = "deny"
file_write = "require_approval"
""".strip(),
        encoding="utf-8",
    )

    config = AgentGateConfig.from_toml_file(config_path)

    assert config.workspace.base_dir == Path("workspace")
    assert config.workspace.public_root == Path("public")
    assert config.workspace.private_root == Path("private")
    assert config.policy.private_read == DecisionStatus.DENY
    assert config.policy.file_write == DecisionStatus.REQUIRE_APPROVAL


def test_agentgate_config_rejects_malformed_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "agentgate.toml"
    config_path.write_text("[workspace", encoding="utf-8")

    with pytest.raises(AgentGateConfigError):
        AgentGateConfig.from_toml_file(config_path)
