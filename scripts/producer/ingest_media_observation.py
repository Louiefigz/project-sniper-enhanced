"""Per-read source identity collection; unchanged admission JSON remains authoritative."""
from __future__ import annotations

import json
from dataclasses import dataclass

from headless.external_media_verification import (
    SourceVerificationRuntime, VerifiedSnapshotIdentity, assert_verified_snapshots,
)
from ingest_admission_io import canonical_bytes


@dataclass(frozen=True)
class VerifiedExecutionMedia:
    """Immutable initial-read evidence, never a replacement source-set receipt."""

    entries_json: bytes
    snapshots: tuple[VerifiedSnapshotIdentity, ...]

    def entries(self) -> list[dict]:
        """Return a fresh copy of the exact originally verified closed entry values."""
        return json.loads(self.entries_json)


class SourceVerificationCapture:
    """Private one-read collector; pending identities are not a successful result."""

    def __init__(self, runtime: SourceVerificationRuntime) -> None:
        """Begin a local capture without creating a clock or source/admission work."""
        if type(runtime) is not SourceVerificationRuntime:
            raise RuntimeError("source capture requires its original verification runtime")
        runtime.check()
        self.runtime = runtime
        self._pending: dict[str, VerifiedSnapshotIdentity] = {}
        self._finished = False

    def add(self, value: VerifiedSnapshotIdentity) -> None:
        """Retain only a completed same-pass snapshot observation, including duplicates exactly."""
        self.runtime.check()
        if self._finished or type(value) is not VerifiedSnapshotIdentity:
            raise RuntimeError("source capture is closed or received an invalid observation")
        prior = self._pending.get(value.path)
        if prior is not None and prior != value:
            raise RuntimeError("source capture snapshot identity changed between admitted rows")
        self._pending[value.path] = value

    def finish(self, entries: list[dict]) -> VerifiedExecutionMedia:
        """Commit only after whole source-set, projection and requested-media checks succeed."""
        if self._finished:
            raise RuntimeError("source capture cannot be completed or reused twice")
        self._finished = True
        self.runtime.check()
        expected = {}
        for entry in entries:
            key = entry["snapshotPath"]
            identity = (entry["sha256"], entry["sizeBytes"])
            if key in expected and expected[key] != identity:
                raise RuntimeError("source capture entries disagree on snapshot byte identity")
            expected[key] = identity
        if set(expected) != set(self._pending):
            raise RuntimeError("source capture did not observe exactly the complete source set")
        rows = tuple(self._pending[path] for path in sorted(expected))
        if any((row.sha256, row.size_bytes) != expected[row.path] for row in rows):
            raise RuntimeError("source capture bytes disagree with the original source-set entries")
        raw = canonical_bytes(entries)
        assert_verified_snapshots(rows, self.runtime)
        return VerifiedExecutionMedia(raw, rows)

    def abort(self) -> None:
        """Fence partial failed verification; never hand it to a subsequent execution."""
        self._finished = True
        self._pending.clear()
