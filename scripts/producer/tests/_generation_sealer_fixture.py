"""Mutable staging and empty authority fixture for generation sealer tests."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from _common import pl  # noqa: F401
from _generation_reader_fixture import (
    ATTEMPT,
    COMMIT_DOMAIN,
    GENERATION,
    UNIT,
    _profile_files,
    canonical,
    write,
)
from headless.generation_sealer_types import GenerationSealRequestV1


class SealerFixture:
    """One complete R0-shaped mutable payload and an unbound authority root."""

    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.staging = self.root / "staging"
        self.destination = self.root / "materialized"
        self.authority.mkdir(mode=0o700)
        self.staging.mkdir(mode=0o700)
        self.files, self.classes = _profile_files()
        self._write_staging()
        self.commit_json = canonical(self.commit_document())

    def _write_staging(self) -> None:
        for relative, raw in self.files.items():
            path = self.staging / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.parent.chmod(0o700)
            write(path, raw, 0o600)

    def commit_document(self) -> dict:
        rows = []
        for path in sorted(self.files):
            raw = self.files[path]
            rows.append(
                {
                    "artifactClass": self.classes[path],
                    "path": path,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "sizeBytes": len(raw),
                }
            )
        return {
            "approvedParentPath": "authority/approved-parent.json",
            "attemptId": ATTEMPT,
            "authorityId": "authority-mp4-v1",
            "executionPolicyId": "2" * 64,
            "expectedParent": None,
            "fallbackPolicyId": "5" * 64,
            "files": rows,
            "generationId": GENERATION,
            "qualityPolicyId": "4" * 64,
            "repairPolicyId": "3" * 64,
            "requestDigest": "1" * 64,
            "schemaVersion": 1,
            "unitId": UNIT,
        }

    def request(
        self, commit_json: bytes | None = None
    ) -> GenerationSealRequestV1:
        return GenerationSealRequestV1(
            str(self.authority),
            str(self.staging),
            self.commit_json if commit_json is None else commit_json,
        )

    def final(self) -> Path:
        return self.authority / "generations" / GENERATION

    def pending(self) -> Path:
        return self.authority / "generations" / f".seal.{GENERATION}.pending"

    def publish_for_reader(self) -> None:
        digest = hashlib.sha256(COMMIT_DOMAIN + self.commit_json).hexdigest()
        current = {
            "authorityId": "authority-mp4-v1",
            "commitDigest": digest,
            "generationId": GENERATION,
            "publicationSeq": 1,
            "schemaVersion": 1,
        }
        write(self.authority / "CURRENT", canonical(current), 0o600)
        write(self.authority / ".publish.mutex", b"", 0o600)
        self.destination.mkdir(mode=0o700)

    def changed_commit(self, relative: str, raw: bytes) -> bytes:
        document = self.commit_document()
        for row in document["files"]:
            if row["path"] == relative:
                row["sizeBytes"] = len(raw)
                row["sha256"] = hashlib.sha256(raw).hexdigest()
        return canonical(document)

    def close(self) -> None:
        self.temp.cleanup()
