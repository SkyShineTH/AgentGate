from __future__ import annotations

from pathlib import Path

from agentgate.policy import PolicyEngine
from agentgate.schemas import DecisionStatus, RiskLevel
from agentgate.workspace import WorkspaceBoundary


def engine(tmp_path: Path) -> PolicyEngine:
    public = tmp_path / "examples" / "workspace" / "public"
    private = tmp_path / "examples" / "workspace" / "private"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    return PolicyEngine(
        WorkspaceBoundary(
            base_dir=tmp_path,
            public_root=public,
            private_root=private,
        )
    )


def request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": "req_test",
        "actor": "demo-agent",
        "tool": "file.read",
        "action": "read",
        "resource": "examples/workspace/public/note.txt",
        "input": {},
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def test_public_read_allowed(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(request())

    assert decision.status == DecisionStatus.ALLOW
    assert decision.risk == RiskLevel.LOW
    assert decision.matched_rule == "public_read_allowed"


def test_private_read_requires_approval(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(
        request(resource="examples/workspace/private/note.txt")
    )

    assert decision.status == DecisionStatus.REQUIRE_APPROVAL
    assert decision.matched_rule == "private_read_requires_approval"


def test_write_requires_approval(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(
        request(
            tool="file.write",
            action="write",
            resource="examples/workspace/private/note.txt",
            input={"content": "synthetic note"},
        )
    )

    assert decision.status == DecisionStatus.REQUIRE_APPROVAL
    assert decision.matched_rule == "file_write_requires_approval"


def test_delete_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(request(tool="file.delete", action="delete"))

    assert decision.status == DecisionStatus.DENY
    assert decision.risk == RiskLevel.CRITICAL
    assert decision.matched_rule == "delete_denied"


def test_shell_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(
        request(
            tool="shell.execute",
            action="execute",
            resource="local-shell",
            input={"command": "echo synthetic-demo"},
        )
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "shell_denied_by_default"


def test_unknown_tool_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(request(tool="browser.open", action="open"))

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "unknown_tool_denied"


def test_unknown_action_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(request(action="remove"))

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "unknown_action_denied"


def test_path_outside_workspace_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(request(resource="outside.txt"))

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "path_outside_workspace_denied"


def test_path_traversal_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(
        request(resource="examples/workspace/public/../private/note.txt")
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "path_traversal_denied"


def test_likely_secret_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(
        request(tool="file.write", action="write", input={"password": "placeholder"})
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.risk == RiskLevel.CRITICAL
    assert decision.matched_rule == "secret_input_denied"


def test_authorization_header_secret_denied(tmp_path: Path) -> None:
    decision = engine(tmp_path).evaluate(
        request(
            tool="file.write",
            action="write",
            input={"headers": {"Authorization": "Bearer synthetic-token-value"}},
        )
    )

    assert decision.status == DecisionStatus.DENY
    assert decision.risk == RiskLevel.CRITICAL
    assert decision.matched_rule == "secret_input_denied"


def test_malformed_request_denied(tmp_path: Path) -> None:
    malformed = request()
    malformed.pop("actor")

    decision = engine(tmp_path).evaluate(malformed)

    assert decision.status == DecisionStatus.DENY
    assert decision.matched_rule == "malformed_request_denied"
    assert decision.request_id == "req_test"
