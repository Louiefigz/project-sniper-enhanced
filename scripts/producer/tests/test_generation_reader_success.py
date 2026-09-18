from __future__ import annotations

import fcntl
import os
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _generation_reader_fixture import GENERATION, Fixture
import headless.generation_reader as reader_module
from headless.generation_reader import read_current_generation


class GenerationReaderSuccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_materializes_exact_recursive_manifest_and_releases_lock(self) -> None:
        fixture = self.fixture
        with read_current_generation(
            str(fixture.authority), str(fixture.destination)
        ) as resolved:
            self.assertEqual(resolved.current.generation_id, GENERATION)
            self.assertEqual(resolved.commit.generation_id, GENERATION)
            self.assertEqual(set(resolved.materialized), set(fixture.files))
            self.assertEqual(set(resolved.materialized_snapshots), set(fixture.files))
            for relative, expected in fixture.files.items():
                copied = Path(resolved.materialized[relative])
                self.assertTrue(copied.is_absolute())
                self.assertEqual(copied.read_bytes(), expected)
                self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
                observed = reader_module._snapshot(copied.stat())
                self.assertEqual(resolved.materialized_snapshots[relative], observed)
            self.assertFalse((fixture.destination / "commit.json").exists())
            lock_fd = os.open(fixture.authority / ".publish.mutex", os.O_RDWR)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

    def test_result_mapping_is_immutable(self) -> None:
        with read_current_generation(
            str(self.fixture.authority), str(self.fixture.destination)
        ) as resolved:
            with self.assertRaises(TypeError):
                resolved.materialized["new"] = "/tmp/new"  # type: ignore[index]
            with self.assertRaises(TypeError):
                resolved.materialized_snapshots["new"] = ()  # type: ignore[index]

    def test_publish_lock_is_held_during_materialization(self) -> None:
        observed = []
        original = reader_module._stream

        def checking_stream(source_fd: int, destination_fd: int | None):
            if destination_fd is not None and not observed:
                lock_fd = os.open(self.fixture.authority / ".publish.mutex", os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append(True)
                finally:
                    os.close(lock_fd)
            return original(source_fd, destination_fd)

        with mock.patch.object(reader_module, "_stream", checking_stream):
            with read_current_generation(
                str(self.fixture.authority), str(self.fixture.destination)
            ):
                pass
        self.assertEqual(observed, [True])


if __name__ == "__main__":
    unittest.main()
