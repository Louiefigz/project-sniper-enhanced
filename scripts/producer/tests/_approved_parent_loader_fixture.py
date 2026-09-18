"""Exact sealed filesystem fixture for approved-parent loader tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import GENERATION
from headless.media_probe import ProbeResultV1


def _write(path: Path, raw: bytes, mode: int) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


class ApprovedParentAuthorityFixture:
    """One private authority root, generation, and empty materialization root."""

    def __init__(self, scenario: str = "success") -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.materialization = self.root / "materialization"
        self.generation = self.authority / "generations" / GENERATION
        self.documents = AuthorityDocuments(scenario)
        self._create_tree()
        self._write_generation()
        self._write_publication()

    def _create_tree(self) -> None:
        self.authority.mkdir(mode=0o700)
        (self.authority / "generations").mkdir(mode=0o700)
        self.generation.mkdir(mode=0o700)
        self.materialization.mkdir(mode=0o700)
        for relative in self.documents.files:
            (self.generation / relative).parent.mkdir(
                mode=0o700, parents=True, exist_ok=True
            )

    def _write_generation(self) -> None:
        for relative, raw in self.documents.files.items():
            _write(self.generation / relative, raw, 0o400)
        _write(self.generation / "commit.json", self.documents.commit_raw, 0o400)
        directories = tuple(
            path for path in self.generation.rglob("*") if path.is_dir()
        )
        for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            path.chmod(0o500)
        self.generation.chmod(0o500)

    def _write_publication(self) -> None:
        _write(self.authority / "CURRENT", self.documents.current_raw, 0o600)
        _write(self.authority / ".publish.mutex", b"", 0o600)

    def base_probe(self) -> ProbeResultV1:
        """Return exact base-byte identity plus its admitted timeline facts."""
        ref = self.documents.artifact_ref("base-media-v1")
        return ProbeResultV1(
            ref.sha256,
            ref.size_bytes,
            1080,
            1920,
            4.0,
            30,
            1,
            120,
            "h264",
            "yuv420p",
            "High",
            "aac",
        )

    def close(self) -> None:
        self.temp.cleanup()
