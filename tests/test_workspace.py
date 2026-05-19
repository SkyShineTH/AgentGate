from __future__ import annotations

from pathlib import Path

from agentgate.workspace import WorkspaceBoundary, WorkspaceKind


def workspace_boundary(tmp_path: Path) -> WorkspaceBoundary:
    public = tmp_path / "examples" / "workspace" / "public"
    private = tmp_path / "examples" / "workspace" / "private"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    return WorkspaceBoundary(
        base_dir=tmp_path,
        public_root=public,
        private_root=private,
    )


def test_resolves_public_workspace_path(tmp_path: Path) -> None:
    boundary = workspace_boundary(tmp_path)

    result = boundary.resolve("examples/workspace/public/note.txt")

    assert result.allowed is True
    assert result.workspace_kind == WorkspaceKind.PUBLIC


def test_resolves_private_workspace_path(tmp_path: Path) -> None:
    boundary = workspace_boundary(tmp_path)

    result = boundary.resolve("examples/workspace/private/note.txt")

    assert result.allowed is True
    assert result.workspace_kind == WorkspaceKind.PRIVATE


def test_denies_path_traversal(tmp_path: Path) -> None:
    boundary = workspace_boundary(tmp_path)

    result = boundary.resolve("examples/workspace/public/../private/note.txt")

    assert result.allowed is False
    assert result.matched_rule == "path_traversal_denied"


def test_denies_absolute_path_outside_workspace(tmp_path: Path) -> None:
    boundary = workspace_boundary(tmp_path)
    outside = tmp_path.parent / "outside.txt"

    result = boundary.resolve(str(outside))

    assert result.allowed is False
    assert result.matched_rule == "path_outside_workspace_denied"


def test_allows_absolute_path_inside_public_workspace(tmp_path: Path) -> None:
    boundary = workspace_boundary(tmp_path)
    inside = tmp_path / "examples" / "workspace" / "public" / "note.txt"

    result = boundary.resolve(str(inside))

    assert result.allowed is True
    assert result.workspace_kind == WorkspaceKind.PUBLIC
