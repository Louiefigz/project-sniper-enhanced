"""Sealed selected-CURRENT filesystem fixture for versioned loader tests."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from _approved_parent_loader_values import canonical

_COMMIT_DOMAIN = b"sniper-mp4-generation-commit-v1\0"


def _write(path: Path, raw: bytes, mode: int) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


class VersionedDiskFixture:
    """One immutable generation selected by one mutable CURRENT pointer."""

    def __init__(self, commit: object, files: dict[str, bytes], sequence: int) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.materialization = self.root / "materialization"
        self.commit = commit
        self.files = dict(files)
        self.generation = self.authority / "generations" / commit.generation_id
        self._create_tree()
        self._write_generation()
        self._write_current(sequence)

    def _create_tree(self) -> None:
        self.authority.mkdir(mode=0o700)
        (self.authority / "generations").mkdir(mode=0o700)
        self.generation.mkdir(mode=0o700)
        self.materialization.mkdir(mode=0o700)
        for relative in self.files:
            (self.generation / relative).parent.mkdir(
                mode=0o700, parents=True, exist_ok=True
            )

    def _write_generation(self) -> None:
        for relative, raw in self.files.items():
            _write(self.generation / relative, raw, 0o400)
        _write(self.generation / "commit.json", self.commit.document_json, 0o400)
        directories = tuple(
            path for path in self.generation.rglob("*") if path.is_dir()
        )
        ordered = sorted(directories, key=lambda item: len(item.parts), reverse=True)
        for path in ordered:
            path.chmod(0o500)
        self.generation.chmod(0o500)

    def _write_current(self, sequence: int) -> None:
        document = {
            "schemaVersion": 1,
            "authorityId": self.commit.authority_id,
            "publicationSeq": sequence,
            "generationId": self.commit.generation_id,
            "commitDigest": self.commit.commit_digest,
        }
        _write(self.authority / "CURRENT", canonical(document), 0o600)
        _write(self.authority / ".publish.mutex", b"", 0o600)

    def corrupt_artifact(self, relative: str, raw: bytes) -> None:
        """Replace one source artifact without updating its committed digest."""
        target = self.generation / relative
        self.generation.chmod(0o700)
        target.parent.chmod(0o700)
        target.chmod(0o600)
        _write(target, raw, 0o400)
        target.parent.chmod(0o500)
        self.generation.chmod(0o500)

    def replace_with_symlink(self, relative: str) -> None:
        """Replace one sealed manifest leaf with an unsafe symlink."""
        target = self.generation / relative
        outside = self.root / "outside"
        _write(outside, self.files[relative], 0o400)
        self.generation.chmod(0o700)
        target.parent.chmod(0o700)
        target.unlink()
        target.symlink_to(outside)
        target.parent.chmod(0o500)
        self.generation.chmod(0o500)

    def close(self) -> None:
        self.temp.cleanup()


def assert_commit_files_match(commit: object, files: dict[str, bytes]) -> None:
    """Fail fixture construction when committed and supplied payloads diverge."""
    rows = {row.path: row for row in commit.files}
    if set(rows) != set(files):
        raise AssertionError("fixture files are not the commit closure")
    for path, raw in files.items():
        identity = (len(raw), hashlib.sha256(raw).hexdigest())
        if identity != (rows[path].size_bytes, rows[path].sha256):
            raise AssertionError(f"fixture bytes differ from commit: {path}")
