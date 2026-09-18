"""Collision-free manifest path tree shared by generation readers/sealers."""

from __future__ import annotations

from dataclasses import dataclass, field

from .generation_reader_fs import GenerationReadError
from .generation_schema import GenerationCommitV1, GenerationManifestRowV1


@dataclass
class _Tree:
    children: dict[str, "_Tree"] = field(default_factory=dict)
    row: GenerationManifestRowV1 | None = None


def _insert_row(root: _Tree, row: GenerationManifestRowV1) -> None:
    node = root
    for part in row.path.split("/"):
        if node.row is not None:
            raise GenerationReadError("manifest path has a file prefix")
        node = node.children.setdefault(part, _Tree())
    if node.row is not None or node.children:
        raise GenerationReadError("manifest paths collide")
    node.row = row


def manifest_tree(commit: GenerationCommitV1) -> _Tree:
    """Build one exact tree and reject file/directory prefix collisions."""
    root = _Tree()
    for row in commit.files:
        _insert_row(root, row)
    return root
