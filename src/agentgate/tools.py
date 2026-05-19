from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agentgate.registry import ToolRegistry
from agentgate.schemas import ToolRequest
from agentgate.workspace import WorkspaceBoundary


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    result_status: str
    tool: str
    action: str
    resource: str
    message: str
    bytes_processed: int | None = None


class ToolExecutor:
    def __init__(
        self,
        workspace: WorkspaceBoundary | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.workspace = workspace or WorkspaceBoundary.default()
        self.registry = registry or ToolRegistry.default()

    @classmethod
    def default(cls) -> "ToolExecutor":
        return cls()

    def execute(
        self, request: ToolRequest, *, authorized: bool = False
    ) -> ExecutionResult:
        if not authorized:
            return self._result(
                request,
                result_status="denied",
                message=(
                    "Tool execution requires an allow decision or approved request."
                ),
            )

        tool = self.registry.get(request.tool)
        if tool is None or not tool.supports_action(request.action):
            return self._result(
                request,
                result_status="denied",
                message="No executor is registered for this tool.",
            )

        if request.tool == "shell.execute":
            return self._result(
                request,
                result_status="denied",
                message="Shell execution is not implemented by AgentGate.",
            )

        if request.tool == "file.delete":
            return self._result(
                request,
                result_status="denied",
                message="File delete execution is denied by default.",
            )

        boundary = self.workspace.resolve(request.resource)
        if not boundary.allowed or boundary.normalized_path is None:
            return self._result(
                request,
                result_status="denied",
                message=boundary.reason,
            )

        if request.tool == "file.read":
            return self._read(request, boundary.normalized_path)

        if tool.has_side_effects and tool.executable:
            return self._write(request, boundary.normalized_path)

        return self._result(
            request,
            result_status="denied",
            message="No executor is registered for this tool.",
        )

    def _read(self, request: ToolRequest, path: Path) -> ExecutionResult:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return self._result(
                request,
                result_status="failed",
                message=f"File read failed: {exc}",
            )
        return self._result(
            request,
            result_status="completed",
            message="File read completed. Content is not included in the result.",
            bytes_processed=len(content.encode("utf-8")),
        )

    def _write(self, request: ToolRequest, path: Path) -> ExecutionResult:
        content = request.input.get("content")
        if not isinstance(content, str):
            return self._result(
                request,
                result_status="failed",
                message="File write input must include string field 'content'.",
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if request.tool == "file.append":
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(content)
            else:
                path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return self._result(
                request,
                result_status="failed",
                message=f"File write failed: {exc}",
            )

        return self._result(
            request,
            result_status="completed",
            message="File write completed.",
            bytes_processed=len(content.encode("utf-8")),
        )

    @staticmethod
    def _result(
        request: ToolRequest,
        *,
        result_status: str,
        message: str,
        bytes_processed: int | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            request_id=request.request_id,
            result_status=result_status,
            tool=request.tool,
            action=request.action,
            resource=request.resource,
            message=message,
            bytes_processed=bytes_processed,
        )
