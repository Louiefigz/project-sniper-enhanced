"""Three-generation selected-lineage fixture for historical resolver tests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import (
    ATTEMPT,
    AUTHORITY,
    COMMIT_DOMAIN,
    EXECUTION,
    FALLBACK,
    QUALITY,
    REPAIR,
    REQUEST,
    UNIT,
    artifact_path,
    canonical,
)
from headless.generation_schema import GenerationCommitV1, parse_generation_commit
from headless.generation_verification import payload_manifest_digest
from headless.repair_intent import ParentRefV1

GENERATION_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "44444444-4444-4444-8444-444444444444",
    "55555555-5555-4555-8555-555555555555",
)
ORPHAN_ID = "66666666-6666-4666-8666-666666666666"


def _write(path: Path, raw: bytes, mode: int) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


def _parent_document(parent: ParentRefV1 | None) -> dict | None:
    if parent is None:
        return None
    return {
        "authorityId": parent.authority_id,
        "publicationSeq": parent.publication_seq,
        "generationId": parent.generation_id,
        "commitDigest": parent.commit_digest,
        "planDigest": parent.plan_digest,
    }


def _ref(raw: bytes, path: str) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


@dataclass
class BuiltGeneration:
    publication_seq: int
    generation_id: str
    files: dict[str, bytes]
    classes: dict[str, str]
    commit: GenerationCommitV1
    commit_raw: bytes
    plan_digest: str

    def ref(self) -> ParentRefV1:
        return ParentRefV1(
            AUTHORITY,
            self.publication_seq,
            self.generation_id,
            self.commit.commit_digest,
            self.plan_digest,
        )


def _rows(files: dict[str, bytes], classes: dict[str, str]) -> list[dict]:
    return [
        {
            "artifactClass": classes[path],
            "path": path,
            "sha256": hashlib.sha256(files[path]).hexdigest(),
            "sizeBytes": len(files[path]),
        }
        for path in sorted(files)
    ]


def _commit_document(
    generation_id: str,
    parent: ParentRefV1 | None,
    files: dict[str, bytes],
    classes: dict[str, str],
) -> dict:
    return {
        "schemaVersion": 1,
        "authorityId": AUTHORITY,
        "generationId": generation_id,
        "attemptId": ATTEMPT,
        "unitId": UNIT,
        "requestDigest": REQUEST,
        "executionPolicyId": EXECUTION,
        "repairPolicyId": REPAIR,
        "qualityPolicyId": QUALITY,
        "fallbackPolicyId": FALLBACK,
        "expectedParent": _parent_document(parent),
        "approvedParentPath": artifact_path("approved-parent-v1"),
        "files": _rows(files, classes),
    }


def _verification(
    generation_id: str, files: dict[str, bytes], provisional: GenerationCommitV1
) -> bytes:
    approved_path = artifact_path("approved-parent-v1")
    payload = tuple(
        row
        for row in provisional.files
        if row.artifact_class != "generation-verification-v1"
    )
    document = {
        "schemaVersion": 1,
        "status": "pass",
        "profile": "deterministic-mp4-r0-v1",
        "authorityId": AUTHORITY,
        "generationId": generation_id,
        "attemptId": ATTEMPT,
        "unitId": UNIT,
        "requestDigest": REQUEST,
        "executionPolicyId": EXECUTION,
        "repairPolicyId": REPAIR,
        "qualityPolicyId": QUALITY,
        "fallbackPolicyId": FALLBACK,
        "approvedParent": _ref(files[approved_path], approved_path),
        "payloadManifestDigest": payload_manifest_digest(payload),
    }
    return canonical(document)


def build_generation(
    generation_id: str, publication_seq: int, parent: ParentRefV1 | None
) -> BuiltGeneration:
    source = AuthorityDocuments()
    files, classes = dict(source.files), dict(source.classes)
    approved_path = artifact_path("approved-parent-v1")
    descriptor = json.loads(files[approved_path])
    descriptor["identity"]["generationId"] = generation_id
    files[approved_path] = canonical(descriptor)
    document = _commit_document(generation_id, parent, files, classes)
    provisional = parse_generation_commit(canonical(document))
    verification_path = artifact_path("generation-verification-v1")
    files[verification_path] = _verification(generation_id, files, provisional)
    raw = canonical(_commit_document(generation_id, parent, files, classes))
    commit = parse_generation_commit(raw)
    return BuiltGeneration(
        publication_seq,
        generation_id,
        files,
        classes,
        commit,
        raw,
        descriptor["plan"]["approvedPlanDigest"],
    )


class HistoricalAuthorityFixture:
    """Selected three-node chain plus optional valid orphaned fork."""

    def __init__(self, include_orphan: bool = False) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.destination = self.root / "materialization"
        self.generations_root = self.authority / "generations"
        self.generations = self._build_selected()
        self.orphan = (
            build_generation(ORPHAN_ID, 2, self.generations[0].ref())
            if include_orphan
            else None
        )
        self._write_tree()

    def _build_selected(self) -> list[BuiltGeneration]:
        values, parent = [], None
        for sequence, generation_id in enumerate(GENERATION_IDS, start=1):
            generation = build_generation(generation_id, sequence, parent)
            values.append(generation)
            parent = generation.ref()
        return values

    def _write_tree(self) -> None:
        self.authority.mkdir(mode=0o700)
        self.generations_root.mkdir(mode=0o700)
        self.destination.mkdir(mode=0o700)
        for generation in self.generations + ([self.orphan] if self.orphan else []):
            self._write_generation(generation)
        self._write_current()
        _write(self.authority / ".publish.mutex", b"", 0o600)

    def _write_generation(self, generation: BuiltGeneration) -> None:
        root = self.generations_root / generation.generation_id
        root.mkdir(mode=0o700)
        for relative, raw in generation.files.items():
            target = root / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write(target, raw, 0o400)
        _write(root / "commit.json", generation.commit_raw, 0o400)
        directories = tuple(path for path in root.rglob("*") if path.is_dir())
        for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            path.chmod(0o500)
        root.chmod(0o500)

    def _write_current(self) -> None:
        current = self.generations[-1]
        document = {
            "schemaVersion": 1,
            "authorityId": AUTHORITY,
            "publicationSeq": current.publication_seq,
            "generationId": current.generation_id,
            "commitDigest": current.commit.commit_digest,
        }
        _write(self.authority / "CURRENT", canonical(document), 0o600)

    def requested(self, index: int) -> ParentRefV1:
        return self.generations[index].ref()

    def generation_path(self, index: int) -> Path:
        return self.generations_root / self.generations[index].generation_id

    def rewrite(self, index: int, mutate) -> None:
        document = json.loads(self.generations[index].commit_raw)
        mutate(document)
        self._replace_commit(index, canonical(document))
        for child_index in range(index + 1, len(self.generations)):
            child = json.loads(self.generations[child_index].commit_raw)
            child["expectedParent"] = _parent_document(
                self.generations[child_index - 1].ref()
            )
            self._replace_commit(child_index, canonical(child))
        self._write_current()

    def _replace_commit(self, index: int, raw: bytes) -> None:
        generation = self.generations[index]
        root = self.generation_path(index)
        root.chmod(0o700)
        target = root / "commit.json"
        target.chmod(0o600)
        _write(target, raw, 0o400)
        root.chmod(0o500)
        generation.commit_raw = raw
        generation.commit = parse_generation_commit(raw)

    def replace_current_inode(self) -> None:
        current = self.authority / "CURRENT"
        replacement = self.authority / ".CURRENT.new"
        _write(replacement, current.read_bytes(), 0o600)
        os.replace(replacement, current)

    def close(self) -> None:
        self.temp.cleanup()
