"""Filesystem writer for real selected and unselected versioned history."""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

from _approved_parent_loader_values import canonical
from _versioned_history_fixture import (
    _FORK_GENERATION,
    _V2_ATTEMPT,
    HistoryPayload,
    _v2_payload,
    mixed_payloads,
)
from headless.generation_schema import parse_generation_commit
from headless.versioned_parent_authority import ParentAuthorityV2


def _write(path: Path, raw: bytes, mode: int) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


def _relabel_head(payload: HistoryPayload) -> HistoryPayload:
    document = json.loads(payload.commit.document_json)
    row = next(
        value
        for value in document["files"]
        if value["path"] == document["approvedParentPath"]
    )
    row["artifactClass"] = "approved-parent-v1"
    commit = parse_generation_commit(canonical(document))
    return dataclasses.replace(payload, commit=commit)


class VersionedHistoryTreeFixture:
    """One selected mixed chain plus an optional unselected fork."""

    def __init__(self, scenario: str = "success", include_fork: bool = False) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        values = mixed_payloads(
            scenario == "wrong-parent-receipt",
            scenario == "cycle",
            scenario == "wrong-genesis-receipt-kind",
        )
        if scenario == "wrong-genesis-tail":
            values = (values[0],)
        if scenario == "class-relabel":
            values = (*values[:-1], _relabel_head(values[-1]))
        self.payloads = values
        self._create(include_fork)
        sequence = self._sequence(scenario)
        self._write_current(sequence)

    def _sequence(self, scenario: str) -> int:
        if scenario == "wrong-genesis-tail":
            return 2
        if scenario == "bad-sequence":
            return 5
        return 4

    def _create(self, include_fork: bool) -> None:
        self.authority.mkdir(mode=0o700)
        (self.authority / "generations").mkdir(mode=0o700)
        for payload in self.payloads:
            self._write_payload(payload)
        if include_fork:
            genesis = self.payloads[0]
            authority = ParentAuthorityV2(
                "genesis-origin", genesis.receipt_class, genesis.receipt
            )
            fork = _v2_payload(genesis.ref(1), authority, _FORK_GENERATION, _V2_ATTEMPT)
            self._write_payload(fork)
        _write(self.authority / ".publish.mutex", b"", 0o600)

    def _write_payload(self, payload: HistoryPayload) -> None:
        root = self.authority / "generations" / payload.commit.generation_id
        root.mkdir(mode=0o700)
        for relative, raw in payload.files.items():
            target = root / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write(target, raw, 0o400)
        _write(root / "commit.json", payload.commit.document_json, 0o400)
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda value: len(value.parts),
            reverse=True,
        )
        for path in directories:
            path.chmod(0o500)
        root.chmod(0o500)

    def _write_current(self, sequence: int) -> None:
        head = self.payloads[-1].commit
        document = {
            "schemaVersion": 1,
            "authorityId": head.authority_id,
            "publicationSeq": sequence,
            "generationId": head.generation_id,
            "commitDigest": head.commit_digest,
        }
        _write(self.authority / "CURRENT", canonical(document), 0o600)

    def corrupt_head_artifact(self) -> None:
        head = self.payloads[-1]
        relative = head.commit.approved_parent_path
        target = self.authority / "generations" / head.commit.generation_id / relative
        generation = target.parents[len(Path(relative).parts) - 1]
        generation.chmod(0o700)
        target.parent.chmod(0o700)
        target.chmod(0o600)
        size = len(target.read_bytes())
        _write(target, b"x" * size, 0o400)
        target.parent.chmod(0o500)
        generation.chmod(0o500)

    def close(self) -> None:
        self.temp.cleanup()
