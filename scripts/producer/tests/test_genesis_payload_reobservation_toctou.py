"""Concurrent mutation attacks against genesis payload reobservation."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from _genesis_r1_fixture import genesis_r1_fixture
from _versioned_disk_fixture import VersionedDiskFixture
from headless.genesis_payload_reobservation import (
    GenesisPayloadReobservationError,
    reobserve_genesis_payload,
)
from headless.versioned_generation_reader import (
    read_versioned_current_generation,
)
import headless.generation_reader_fs as reader_fs


def _mutate_same_inode(target: Path, _fixture: VersionedDiskFixture) -> None:
    with target.open("r+b", buffering=0) as handle:
        first = handle.read(1)
        handle.seek(0)
        handle.write(b"x" if first != b"x" else b"y")
        os.fsync(handle.fileno())


def _replace_inode(target: Path, _fixture: VersionedDiskFixture) -> None:
    raw = target.read_bytes()
    target.unlink()
    target.write_bytes(raw)
    target.chmod(0o600)


def _add_hardlink(target: Path, fixture: VersionedDiskFixture) -> None:
    os.link(target, fixture.root / "concurrent-hardlink")


def _add_late_nested_entry(_target: Path, fixture: VersionedDiskFixture) -> None:
    (fixture.materialization / "artifacts" / "late-extra").write_bytes(b"extra")


_MUTATIONS = {
    "same-inode": (2, _mutate_same_inode),
    "replacement": (2, _replace_inode),
    "hardlink": (2, _add_hardlink),
    "late-nested-entry": (33, _add_late_nested_entry),
}


class GenesisPayloadReobservationToctouTests(unittest.TestCase):
    def _assert_concurrent_mutation_rejects(self, mutation: str) -> None:
        value = genesis_r1_fixture()
        fixture = VersionedDiskFixture(value.inputs.commit, value.files, 1)
        target = fixture.materialization / value.inputs.commit.files[0].path
        original, calls = reader_fs._stream, []
        trigger, mutate = _MUTATIONS[mutation]
        try:
            with read_versioned_current_generation(
                str(fixture.authority), str(fixture.materialization)
            ) as selected:

                def attack(fd: int, destination: int | None) -> tuple[int, str]:
                    observed = original(fd, destination)
                    calls.append(os.fstat(fd).st_ino)
                    if len(calls) == trigger:
                        mutate(target, fixture)
                    return observed

                stream_patch = patch.object(reader_fs, "_stream", attack)
                with stream_patch, self.assertRaises(GenesisPayloadReobservationError):
                    reobserve_genesis_payload(selected)
            self.assertGreaterEqual(len(calls), trigger)
        finally:
            fixture.close()

    def test_previously_streamed_artifact_cannot_change_mid_pass(self) -> None:
        for mutation in _MUTATIONS:
            with self.subTest(mutation=mutation):
                self._assert_concurrent_mutation_rejects(mutation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
