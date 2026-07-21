from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.artifact_contract import ArtifactRefV1  # noqa: E402
from headless.generation_artifact_store import (  # noqa: E402
    GenerationArtifactStoreError,
    GenerationArtifactStoreV1,
)
from headless.generation_reader import ResolvedGenerationV1  # noqa: E402
from headless.generation_schema import (  # noqa: E402
    parse_current_pointer,
    parse_generation_commit,
)

GENERATION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
DOMAIN = b"sniper-mp4-generation-commit-v1\0"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


class _Fixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.files = {
            "authority/approved-parent.json": b'{"approved":true}',
            "proof/qc.json": b'{"pass":true}',
        }
        self.paths = self._write_files()
        self.snapshots = {
            relative: self._snapshot(Path(path))
            for relative, path in self.paths.items()
        }
        self.commit = self._commit()
        self.current = self._current()
        self.resolved = ResolvedGenerationV1(
            self.current,
            self.commit,
            MappingProxyType(self.paths),
            MappingProxyType(self.snapshots),
        )

    @staticmethod
    def _snapshot(path: Path) -> tuple[int, ...]:
        info = path.stat(follow_symlinks=False)
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_nlink,
            info.st_uid,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def _write_files(self) -> dict[str, str]:
        paths = {}
        for relative, raw in self.files.items():
            path = self.root / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
            paths[relative] = str(path)
        return paths

    def _commit(self):
        rows = []
        for relative, raw in self.files.items():
            rows.append(
                {
                    "artifactClass": (
                        "approved-parent" if relative.startswith("authority/") else "qc"
                    ),
                    "path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "sizeBytes": len(raw),
                }
            )
        document = {
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
        return parse_generation_commit(_canonical(document))

    def _current(self):
        document = {
            "schemaVersion": 1,
            "authorityId": self.commit.authority_id,
            "publicationSeq": 1,
            "generationId": self.commit.generation_id,
            "commitDigest": self.commit.commit_digest,
        }
        return parse_current_pointer(_canonical(document))

    def ref(self, relative: str) -> ArtifactRefV1:
        row = next(row for row in self.commit.files if row.path == relative)
        return ArtifactRefV1(row.path, row.sha256, row.size_bytes)

    def close(self) -> None:
        self.temp.cleanup()


class GenerationArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_exact_ref_resolves_and_stable_bytes_read(self) -> None:
        fixture = self.fixture
        store = GenerationArtifactStoreV1.from_resolved(fixture.resolved)
        ref = fixture.ref("authority/approved-parent.json")
        self.assertEqual(store.resolve(ref), fixture.paths[ref.relative_path])
        self.assertEqual(store.read(ref, 1024), fixture.files[ref.relative_path])
        row = next(row for row in fixture.commit.files if row.path == ref.relative_path)
        self.assertEqual(store.ref_for_row(row), ref)

    def test_forged_ref_and_read_limit_reject(self) -> None:
        store = GenerationArtifactStoreV1.from_resolved(self.fixture.resolved)
        ref = self.fixture.ref("proof/qc.json")
        forged = ArtifactRefV1(ref.relative_path, "0" * 64, ref.size_bytes)
        with self.assertRaisesRegex(GenerationArtifactStoreError, "manifest"):
            store.resolve(forged)
        with self.assertRaisesRegex(GenerationArtifactStoreError, "limit"):
            store.read(ref, 1)

    def test_forged_resolved_wire_fields_and_cross_root_reject(self) -> None:
        fixture = self.fixture
        wrong = ResolvedGenerationV1(
            fixture.current,
            fixture.commit,
            MappingProxyType(
                {
                    **fixture.paths,
                    "proof/qc.json": str(fixture.root.parent / "proof/qc.json"),
                }
            ),
            fixture.resolved.materialized_snapshots,
        )
        with self.assertRaises(GenerationArtifactStoreError):
            GenerationArtifactStoreV1.from_resolved(wrong)
        forged_current = type(fixture.current)(
            fixture.current.authority_id,
            2,
            fixture.current.generation_id,
            fixture.current.commit_digest,
            fixture.current.document_json,
        )
        wrong = ResolvedGenerationV1(
            forged_current,
            fixture.commit,
            fixture.resolved.materialized,
            fixture.resolved.materialized_snapshots,
        )
        with self.assertRaises(GenerationArtifactStoreError):
            GenerationArtifactStoreV1.from_resolved(wrong)

    def test_post_construction_substitution_rejects_on_read(self) -> None:
        kinds = ("new-inode", "changed", "mode", "symlink", "hardlink")
        for kind in kinds:
            fixture = _Fixture()
            try:
                store = GenerationArtifactStoreV1.from_resolved(fixture.resolved)
                ref = fixture.ref("proof/qc.json")
                target = Path(fixture.paths[ref.relative_path])
                raw = target.read_bytes()
                outside = fixture.root / f"outside-{kind}"
                if kind == "mode":
                    target.chmod(0o644)
                else:
                    target.unlink()
                if kind == "new-inode":
                    target.write_bytes(raw)
                    target.chmod(0o600)
                elif kind == "changed":
                    target.write_bytes(b"X" * len(raw))
                    target.chmod(0o600)
                elif kind == "symlink":
                    outside.write_bytes(raw)
                    target.symlink_to(outside)
                elif kind == "hardlink":
                    outside.write_bytes(raw)
                    outside.chmod(0o600)
                    os.link(outside, target)
                with self.subTest(kind=kind), self.assertRaises(
                    GenerationArtifactStoreError
                ):
                    store.read(ref, 1024)
            finally:
                fixture.close()

    def test_root_mode_and_mapping_identity_are_required(self) -> None:
        fixture = self.fixture
        fixture.root.chmod(0o755)
        with self.assertRaisesRegex(GenerationArtifactStoreError, "root"):
            GenerationArtifactStoreV1.from_resolved(fixture.resolved)


if __name__ == "__main__":
    unittest.main()
