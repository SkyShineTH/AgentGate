from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from agentgate.adapters import (
    AdapterError,
    JsonToolRequestAdapter,
    OpenAIFunctionToolCallAdapter,
)
from agentgate.policy import PolicyEngine
from agentgate.schemas import DecisionStatus, ToolRequest
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


def test_json_adapter_converts_canonical_payload(tmp_path: Path) -> None:
    request = JsonToolRequestAdapter(
        {
            "request_id": "req_json_adapter",
            "actor": "demo-agent",
            "tool": "file.read",
            "action": "read",
            "resource": "examples/workspace/public/note.txt",
            "input": {},
            "metadata": {"source": "json-adapter-test"},
        }
    ).to_tool_request()

    decision = PolicyEngine(workspace(tmp_path)).evaluate(request)

    assert request.request_id == "req_json_adapter"
    assert decision.status == DecisionStatus.ALLOW
    assert decision.matched_rule == "public_read_allowed"


def test_json_adapter_rejects_malformed_payload() -> None:
    with pytest.raises(AdapterError):
        JsonToolRequestAdapter({"tool": "file.read"}).to_tool_request()


@pytest.mark.parametrize("payload", [None, [], "not-an-object"])
def test_json_adapter_rejects_non_mapping_payloads(payload: object) -> None:
    with pytest.raises(AdapterError):
        JsonToolRequestAdapter(payload).to_tool_request()


def test_openai_style_adapter_converts_function_call_dict(tmp_path: Path) -> None:
    tool_call = {
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "agentgate_tool_request",
            "arguments": json.dumps(
                {
                    "tool": "file.append",
                    "action": "append",
                    "resource": "examples/workspace/private/job-tracker.csv",
                    "input": {"content": "Example Co,queued\n"},
                    "metadata": {"scenario": "adapter_write"},
                }
            ),
        },
    }

    request = OpenAIFunctionToolCallAdapter(
        tool_call,
        actor="demo-agent",
    ).to_tool_request()
    decision = PolicyEngine(workspace(tmp_path)).evaluate(request)

    assert request.request_id == "call_abc123"
    assert request.actor == "demo-agent"
    assert request.tool == "file.append"
    assert request.metadata["adapter"] == "openai_function_tool_call"
    assert request.metadata["provider_call_id"] == "call_abc123"
    assert request.metadata["provider_tool_name"] == "agentgate_tool_request"
    assert decision.status == DecisionStatus.REQUIRE_APPROVAL
    assert decision.matched_rule == "file_write_requires_approval"


def test_openai_provider_metadata_does_not_change_policy_decision(
    tmp_path: Path,
) -> None:
    canonical = ToolRequest(
        request_id="req_metadata_isolation",
        actor="demo-agent",
        tool="file.read",
        action="read",
        resource="examples/workspace/public/note.txt",
        input={},
    )
    tool_call = {
        "id": "req_metadata_isolation",
        "function": {
            "name": "agentgate_tool_request",
            "arguments": {
                "tool": "file.read",
                "action": "read",
                "resource": "examples/workspace/public/note.txt",
                "input": {},
                "metadata": {"provider_specific": "ignored-by-policy"},
            },
        },
    }
    adapted = OpenAIFunctionToolCallAdapter(
        tool_call,
        actor="demo-agent",
    ).to_tool_request()
    policy = PolicyEngine(workspace(tmp_path))

    canonical_decision = policy.evaluate(canonical)
    adapted_decision = policy.evaluate(adapted)

    assert adapted.metadata["provider_specific"] == "ignored-by-policy"
    assert adapted.metadata["adapter"] == "openai_function_tool_call"
    assert adapted_decision.status == canonical_decision.status
    assert adapted_decision.risk == canonical_decision.risk
    assert adapted_decision.matched_rule == canonical_decision.matched_rule


def test_openai_style_adapter_supports_mapping_arguments(tmp_path: Path) -> None:
    tool_call = {
        "id": "call_mapping",
        "function": {
            "name": "agentgate_tool_request",
            "arguments": {
                "request_id": "req_mapping_arguments",
                "tool": "file.read",
                "action": "read",
                "resource": "examples/workspace/public/note.txt",
            },
        },
    }

    request = OpenAIFunctionToolCallAdapter(
        tool_call,
        actor="demo-agent",
    ).to_tool_request()
    decision = PolicyEngine(workspace(tmp_path)).evaluate(request)

    assert request.request_id == "req_mapping_arguments"
    assert decision.status == DecisionStatus.ALLOW


@pytest.mark.parametrize(
    "tool_call",
    [
        {},
        {"function": {"name": "agentgate_tool_request", "arguments": "not-json"}},
        {"function": {"name": "agentgate_tool_request", "arguments": []}},
        {"function": {"name": "agentgate_tool_request", "arguments": "{}"}},
        {
            "function": {
                "name": "agentgate_tool_request",
                "arguments": {"tool": "file.read", "action": "read", "input": []},
            }
        },
        None,
        [],
        "not-an-object",
    ],
)
def test_openai_style_adapter_rejects_malformed_calls(
    tool_call: object,
) -> None:
    with pytest.raises(AdapterError):
        OpenAIFunctionToolCallAdapter(
            tool_call,
            actor="demo-agent",
        ).to_tool_request()


def test_importing_core_and_adapters_does_not_require_provider_sdks() -> None:
    agentgate = importlib.import_module("agentgate")
    adapters = importlib.import_module("agentgate.adapters.openai")

    assert hasattr(agentgate, "PolicyEngine")
    assert hasattr(adapters, "OpenAIFunctionToolCallAdapter")
