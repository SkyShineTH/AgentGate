from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class WorkspaceKind(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class WorkspaceResolution:
    allowed: bool
    resource: str
    normalized_path: Path | None
    workspace_kind: WorkspaceKind | None
    reason: str
    matched_rule: str | None


class WorkspaceBoundary:
    """Resolve file resources against the configured public/private workspaces."""

    def __init__(
        self,
        *,
        base_dir: Path,
        public_root: Path,
        private_root: Path,
    ) -> None:
        self.base_dir = base_dir.resolve(strict=False)
        self.public_root = public_root.resolve(strict=False)
        self.private_root = private_root.resolve(strict=False)

    @classmethod
    def default(cls) -> "WorkspaceBoundary":
        repo_root = Path(__file__).resolve().parents[2]
        return cls(
            base_dir=repo_root,
            public_root=repo_root / "examples" / "workspace" / "public",
            private_root=repo_root / "examples" / "workspace" / "private",
        )

    def resolve(self, resource: str) -> WorkspaceResolution:
        if not isinstance(resource, str) or not resource.strip():
            return self._denied(
                resource=str(resource),
                reason="File resource must be a non-empty path.",
                matched_rule="malformed_request_denied",
            )

        if "\x00" in resource:
            return self._denied(
                resource=resource,
                reason="File resource contains an invalid path character.",
                matched_rule="path_outside_workspace_denied",
            )

        raw_path = Path(resource)
        if ".." in raw_path.parts:
            return self._denied(
                resource=resource,
                reason="Path traversal is not allowed.",
                matched_rule="path_traversal_denied",
            )

        candidate = raw_path if raw_path.is_absolute() else self.base_dir / raw_path
        normalized = candidate.resolve(strict=False)

        if self._is_relative_to(normalized, self.public_root):
            return WorkspaceResolution(
                allowed=True,
                resource=resource,
                normalized_path=normalized,
                workspace_kind=WorkspaceKind.PUBLIC,
                reason="Path is inside the public workspace.",
                matched_rule=None,
            )

        if self._is_relative_to(normalized, self.private_root):
            return WorkspaceResolution(
                allowed=True,
                resource=resource,
                normalized_path=normalized,
                workspace_kind=WorkspaceKind.PRIVATE,
                reason="Path is inside the private workspace.",
                matched_rule=None,
            )

        return self._denied(
            resource=resource,
            reason="Path is outside the configured workspace roots.",
            matched_rule="path_outside_workspace_denied",
            normalized_path=normalized,
        )

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _denied(
        *,
        resource: str,
        reason: str,
        matched_rule: str,
        normalized_path: Path | None = None,
    ) -> WorkspaceResolution:
        return WorkspaceResolution(
            allowed=False,
            resource=resource,
            normalized_path=normalized_path,
            workspace_kind=None,
            reason=reason,
            matched_rule=matched_rule,
        )
