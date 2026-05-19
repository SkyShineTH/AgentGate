from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from agentgate.schemas import RiskLevel


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    actions: frozenset[str] = Field(default_factory=frozenset)
    default_risk: RiskLevel
    requires_workspace_path: bool = True
    has_side_effects: bool = False
    executable: bool = True

    def supports_action(self, action: str) -> bool:
        return action in self.actions


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolDefinition]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @classmethod
    def default(cls) -> "ToolRegistry":
        return cls(DEFAULT_TOOL_DEFINITIONS)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def supports_action(self, tool_name: str, action: str) -> bool:
        definition = self.get(tool_name)
        return definition is not None and definition.supports_action(action)

    def write_tools(self) -> frozenset[str]:
        return frozenset(
            tool.name for tool in self._tools.values() if tool.has_side_effects
        )


DEFAULT_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="file.read",
        actions=frozenset({"read"}),
        default_risk=RiskLevel.LOW,
        requires_workspace_path=True,
        has_side_effects=False,
        executable=True,
    ),
    ToolDefinition(
        name="file.write",
        actions=frozenset({"write", "create"}),
        default_risk=RiskLevel.MEDIUM,
        requires_workspace_path=True,
        has_side_effects=True,
        executable=True,
    ),
    ToolDefinition(
        name="file.append",
        actions=frozenset({"append"}),
        default_risk=RiskLevel.MEDIUM,
        requires_workspace_path=True,
        has_side_effects=True,
        executable=True,
    ),
    ToolDefinition(
        name="file.update",
        actions=frozenset({"update"}),
        default_risk=RiskLevel.MEDIUM,
        requires_workspace_path=True,
        has_side_effects=True,
        executable=True,
    ),
    ToolDefinition(
        name="file.delete",
        actions=frozenset({"delete"}),
        default_risk=RiskLevel.CRITICAL,
        requires_workspace_path=True,
        has_side_effects=True,
        executable=False,
    ),
    ToolDefinition(
        name="shell.execute",
        actions=frozenset({"execute"}),
        default_risk=RiskLevel.HIGH,
        requires_workspace_path=False,
        has_side_effects=True,
        executable=False,
    ),
)

WRITE_TOOLS = ToolRegistry.default().write_tools() - frozenset(
    {"file.delete", "shell.execute"}
)
