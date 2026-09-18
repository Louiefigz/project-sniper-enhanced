"""Three exact TEST metadata files; no sidecar, job, source or real resource claim."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from _source_color_staging_read_fixture import SourceColorStagingReadFixture, _raw
from guided_source_color_reservation_read import SourceColorReservationReadContext, read_source_color_reservation


class SourceColorReservationFixture:
    """Reuse inert original claim/input metadata and remove only the TEST sidecar."""

    def __init__(self) -> None:
        """Keep all artifacts beneath one explicitly allocated canonical TEST root."""
        self.staging = SourceColorStagingReadFixture()
        self.root = self.staging.root
        self.reservation_path, self.claim_path, self.input_path = (
            self.staging.reservation_path, self.staging.claim_path, self.staging.input_path)
        self.allowed = frozenset((self.reservation_path, self.claim_path, self.input_path))
        self.refresh()

    def refresh(self) -> None:
        """Publish fresh TEST refs before a new invocation, never during a held read."""
        self.staging.refresh()
        self.staging.reservation["ownerPid"] = 1234
        self.reservation = self.staging.reservation
        self.publish()
        original = self.staging.context
        self.context = SourceColorReservationReadContext(original.opening, original.producer_dir, original.resource_dir,
                                                         self.reservation["sourceColorHash"], original.deadline, original.guard)
        sidecar = self.staging.sidecar_path
        if sidecar not in self.staging.allowed or not sidecar.is_relative_to(self.root) or sidecar.parent.resolve() != sidecar.parent:
            raise AssertionError("TEST sidecar removal escaped its original namespace")
        info = sidecar.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise AssertionError("TEST sidecar removal requires owned regular single-link bytes")
        sidecar.unlink()

    def write(self, path: Path, raw: bytes) -> str:
        """Delegate only three named TEST-root regular-file mutation targets."""
        if path not in self.allowed:
            raise AssertionError("TEST reservation fault target is outside exact three files")
        return self.staging.write(path, raw)

    def publish(self) -> None:
        """Update the explicit raw reservation reference before a fresh invocation."""
        raw = _raw(self.reservation)
        self.write(self.reservation_path, raw)
        self.reference = (self.reservation_path, hashlib.sha256(raw).hexdigest())

    def run(self) -> object:
        """Call actual metadata reader, with no source/process/runtime seams."""
        return read_source_color_reservation(self.reference, self.context)

    def close(self) -> None:
        """Remove only the fixture's exact newly allocated TEST tree."""
        self.staging.close()
