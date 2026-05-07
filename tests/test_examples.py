from __future__ import annotations

import json
from pathlib import Path

from agentgate.policy import PolicyEngine
from agentgate.schemas import DecisionStatus, RiskLevel

ROOT = Path(__file__).resolve().parents[1]


EXAMPLE_EXPECTATIONS = {
    "read_public_file.json": (
        DecisionStatus.ALLOW,
        RiskLevel.LOW,
        "public_read_allowed",
    ),
    "read_private_file_requires_approval.json": (
        DecisionStatus.REQUIRE_APPROVAL,
        RiskLevel.MEDIUM,
        "private_read_requires_approval",
    ),
    "write_private_note_requires_approval.json": (
        DecisionStatus.REQUIRE_APPROVAL,
        RiskLevel.MEDIUM,
        "file_write_requires_approval",
    ),
    "delete_file_denied.json": (
        DecisionStatus.DENY,
        RiskLevel.CRITICAL,
        "delete_denied",
    ),
    "path_traversal_denied.json": (
        DecisionStatus.DENY,
        RiskLevel.HIGH,
        "path_traversal_denied",
    ),
    "shell_denied.json": (
        DecisionStatus.DENY,
        RiskLevel.HIGH,
        "shell_denied_by_default",
    ),
    "unknown_tool_denied.json": (
        DecisionStatus.DENY,
        RiskLevel.HIGH,
        "unknown_tool_denied",
    ),
    "secret_input_denied.json": (
        DecisionStatus.DENY,
        RiskLevel.CRITICAL,
        "secret_input_denied",
    ),
}


def test_example_request_decisions() -> None:
    engine = PolicyEngine.default()

    for filename, (status, risk, matched_rule) in EXAMPLE_EXPECTATIONS.items():
        payload = json.loads((ROOT / "examples" / "requests" / filename).read_text())

        decision = engine.evaluate(payload)

        assert decision.status == status, filename
        assert decision.risk == risk, filename
        assert decision.matched_rule == matched_rule, filename

