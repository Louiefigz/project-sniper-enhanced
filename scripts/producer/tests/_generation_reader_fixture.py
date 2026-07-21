"""Exact R0 authority fixture shared by generation reader tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from _common import pl  # noqa: F401
from headless.generation_profile import R0_GENERATION_ARTIFACT_CLASS_COUNTS

GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
COMMIT_DOMAIN = b"sniper-mp4-generation-commit-v1\0"

_R0_PATHS = {
    "approved-parent-v1": "authority/approved-parent.json",
    "final-media-v1": "media/final.mp4",
    "audit-b-receipt-v1": "proof/qc.json",
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def write(path: Path, data: bytes, mode: int) -> None:
    path.write_bytes(data)
    path.chmod(mode)


def _artifact_path(artifact_class: str, ordinal: int) -> str:
    if ordinal == 0 and artifact_class in _R0_PATHS:
        return _R0_PATHS[artifact_class]
    return f"artifacts/{artifact_class}-{ordinal}.bin"


def _profile_files() -> tuple[dict[str, bytes], dict[str, str]]:
    files, classes = {}, {}
    for artifact_class, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
        for ordinal in range(count):
            path = _artifact_path(artifact_class, ordinal)
            files[path] = f"{artifact_class}:{ordinal}\n".encode("ascii")
            classes[path] = artifact_class
    return files, classes


class Fixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.destination = self.root / "attempt-copy"
        self.generation = self.authority / "generations" / GENERATION
        self.files, self.classes = _profile_files()
        self._make_directories()
        self._write_generation()
        self._write_authority()

    def _make_directories(self) -> None:
        self.authority.mkdir(mode=0o700)
        (self.authority / "generations").mkdir(mode=0o700)
        self.generation.mkdir(mode=0o700)
        self.destination.mkdir(mode=0o700)
        for relative in self.files:
            (self.generation / relative).parent.mkdir(
                mode=0o700, parents=True, exist_ok=True
            )

    def commit_document(self) -> dict:
        rows = []
        for path in sorted(self.files):
            data = self.files[path]
            rows.append(
                {
                    "artifactClass": self.classes[path],
                    "path": path,
                    "sizeBytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        return {
            "schemaVersion": 1,
            "authorityId": "authority-mp4-v1",
            "generationId": GENERATION,
            "attemptId": ATTEMPT,
            "unitId": UNIT,
            "requestDigest": "1" * 64,
            "expectedParent": None,
            "executionPolicyId": "2" * 64,
            "repairPolicyId": "3" * 64,
            "qualityPolicyId": "4" * 64,
            "fallbackPolicyId": "5" * 64,
            "approvedParentPath": "authority/approved-parent.json",
            "files": rows,
        }

    def _commit(self) -> bytes:
        return canonical(self.commit_document())

    def _write_generation(self) -> None:
        for relative, data in self.files.items():
            write(self.generation / relative, data, 0o400)
        write(self.generation / "commit.json", self._commit(), 0o400)
        directories = [path for path in self.generation.rglob("*") if path.is_dir()]
        ordered = sorted(directories, key=lambda value: len(value.parts), reverse=True)
        for path in ordered:
            path.chmod(0o500)
        self.generation.chmod(0o500)

    def _write_authority(self) -> None:
        commit = (self.generation / "commit.json").read_bytes()
        digest = hashlib.sha256(COMMIT_DOMAIN + commit).hexdigest()
        current = {
            "schemaVersion": 1,
            "authorityId": "authority-mp4-v1",
            "publicationSeq": 7,
            "generationId": GENERATION,
            "commitDigest": digest,
        }
        write(self.authority / "CURRENT", canonical(current), 0o600)
        write(self.authority / ".publish.mutex", b"", 0o600)

    def replace_commit(self, document: dict) -> None:
        self.generation.chmod(0o700)
        commit = self.generation / "commit.json"
        commit.chmod(0o600)
        write(commit, canonical(document), 0o400)
        self.generation.chmod(0o500)
        self._write_authority()

    def make_generation_writable(self) -> None:
        self.generation.chmod(0o700)

    def close(self) -> None:
        self.temp.cleanup()
