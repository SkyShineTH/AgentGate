from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest


def test_tool_request_defaults_request_id_and_created_at() -> None:
    request = ToolRequest(
        actor="demo-agent",
        tool="file.read",
        action="read",
        resource="examples/workspace/public/sample_note.txt",
    )

    assert request.request_id.startswith("req_")
    assert request.input == {}
    assert request.metadata == {}
    assert request.created_at.tzinfo is not None


def test_tool_request_rejects_blank_required_fields() -> None:
    with pytest.raises(ValidationError):
        ToolRequest(
            actor=" ",
            tool="file.read",
            action="read",
            resource="examples/workspace/public/sample_note.txt",
        )


def test_tool_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ToolRequest(
            actor="demo-agent",
            tool="file.read",
            action="read",
            resource="examples/workspace/public/sample_note.txt",
            unexpected=True,
        )


def test_decision_serializes_enum_values() -> None:
    decision = Decision(
        request_id="req_test",
        status=DecisionStatus.ALLOW,
        risk=RiskLevel.LOW,
        reason="Allowed.",
        matched_rule="public_read_allowed",
    )

    assert '"status":"allow"' in decision.model_dump_json()
