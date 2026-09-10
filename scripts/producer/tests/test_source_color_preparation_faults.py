"""Original-lifetime/readback faults; filesystem writes require exact TEST-root ownership."""
from __future__ import annotations

import os
import stat
import time
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _source_color_preparation_fixture import SourceColorPreparationFixture
import guided_source_color_preparation as preparation


class SourceColorPreparationFaultTests(unittest.TestCase):
    """Callbacks cannot change parents, source capture, metadata, guard or original time."""

    def setUp(self) -> None:
        """Set up only inert metadata and one original fake clock, never a native process."""
        self.clock = [1000.0]
        clock = patch.object(time, "monotonic", side_effect=lambda: self.clock[0])
        clock.start()
        self.addCleanup(clock.stop)
        self.fixture = SourceColorPreparationFixture()
        self.addCleanup(self.fixture.cleanup)

    def run_preparation(self) -> tuple:
        """Run the real all-or-nothing metadata adapter."""
        fixture = self.fixture
        return preparation.prepare_source_color_jobs(fixture.inputs, fixture.declarations, fixture.context)

    def _owned_file(self, path: Path) -> Path:
        """Validate canonical regular-file/single-link/UID confinement before mutation."""
        root = Path(self.fixture.temporary.name).resolve(strict=True)
        if root != self.fixture.root or path != path.resolve(strict=True) or not path.is_relative_to(root):
            raise RuntimeError("fault target is outside the exact TEST root")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("fault target is not a TEST-owned single-link regular file")
        return path

    def _append(self, path: Path) -> None:
        """Append only after ownership validation, never from generic dependency lists."""
        target = self._owned_file(path)
        target.write_bytes(target.read_bytes() + b"\nTEST fault\n")

    def _final_callback(self, operation: Callable[[], None]) -> None:
        """Run the fault only at the fourth and final whole-context guard call."""
        calls = []

        def guard() -> None:
            """Let all earlier parent/receipt reads finish before this mutation."""
            calls.append(True)
            if len(calls) == 4:
                operation()

        self.fixture.guard.side_effect = guard

    def test_expired_entry_does_not_call_guard_or_read_documents(self) -> None:
        """Budget admission precedes hashing even small metadata or invoking callbacks."""
        self.clock[0] = 1300.0
        with patch.object(preparation, "read_bytes", side_effect=AssertionError("no document reads")), \
                self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            self.run_preparation()
        self.fixture.guard.assert_not_called()

    def test_original_guard_failure_is_not_suppressed(self) -> None:
        """Lost project/resource/tool ownership cannot produce source job data."""
        self.fixture.guard.side_effect = RuntimeError("TEST original tool or project guard lost")
        with self.assertRaisesRegex(RuntimeError, "original tool or project guard lost"):
            self.run_preparation()

    def test_context_deadline_and_callback_replacement_reject_before_reads(self) -> None:
        """Do not consult a renewed cutoff supplied by an original callback."""
        self.fixture.guard.side_effect = lambda: object.__setattr__(self.fixture.context, "deadline", 1600.0)
        with patch.object(preparation, "read_bytes", side_effect=AssertionError("no document reads")), \
                self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            self.run_preparation()

    def test_same_value_new_capture_is_not_the_initial_capture(self) -> None:
        """Original source-hash capture identity cannot be reconstructed or swapped."""
        original = self.fixture.inputs.verified_media
        self.fixture.guard.side_effect = lambda: object.__setattr__(self.fixture.inputs, "verified_media", replace(original))
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            self.run_preparation()

    def test_equal_float_source_size_is_not_original_integer_capture(self) -> None:
        """Coerced mutable record fields are rejected before source/job work."""
        source = self.fixture.inputs.verified_media.snapshots[0]
        self.fixture.guard.side_effect = lambda: object.__setattr__(source, "size_bytes", float(source.size_bytes))
        with self.assertRaisesRegex(RuntimeError, "captured identity is malformed"):
            self.run_preparation()

    def test_last_callback_declaration_mutation_withholds_all_prepared_sources(self) -> None:
        """A first valid prepared source cannot leak when a later original declaration moves."""
        row = self.fixture.declarations["raw-a"]["declaration"]
        self._final_callback(lambda: row.__setitem__("historyState", "unknown"))
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            self.run_preparation()
        self.assertEqual(self.fixture.guard.call_count, 4)

    def test_last_callback_tool_metadata_mutation_withholds_result(self) -> None:
        """Even data-only preparation remains bound to its original input/tool controls."""
        self._final_callback(lambda: self.fixture.inputs.value["pipeline"].__setitem__("TEST", "changed tool"))
        with self.assertRaisesRegex(RuntimeError, "original input/context changed"):
            self.run_preparation()

    def test_last_callback_real_parent_byte_change_is_rejected(self) -> None:
        """The final callback follows raw rereads but still cannot mutate a held parent."""
        self._final_callback(lambda: self._append(self.fixture.root / "project.json"))
        with self.assertRaisesRegex(RuntimeError, "held parent/receipt changed"):
            self.run_preparation()

    def test_last_callback_real_receipt_byte_change_is_rejected(self) -> None:
        """The exact original receipt hash remains bound until the final return."""
        target = self.fixture.producer / self.fixture.entries[0]["admissionReceiptPath"]
        self._final_callback(lambda: self._append(target))
        with self.assertRaisesRegex(RuntimeError, "held parent/receipt changed"):
            self.run_preparation()

    def test_same_inode_source_parent_symlink_swap_is_rejected(self) -> None:
        """Same leaf stat is insufficient when a source parent is replaced by a symlink."""
        store, moved = self.fixture.store, self.fixture.producer / "TEST-moved-original-store"
        self.assertEqual(store.parent.resolve(strict=True), self.fixture.producer)
        self.assertTrue(store.is_relative_to(self.fixture.root))

        def mutate() -> None:
            """Rename only the explicitly created TEST store inside this fixture root."""
            store.rename(moved)
            store.symlink_to(moved, target_is_directory=True)

        self._final_callback(mutate)
        with self.assertRaisesRegex(RuntimeError, "canonical"):
            self.run_preparation()

    def test_last_callback_original_expiry_cannot_become_prepared_success(self) -> None:
        """No separate deadline is created for final metadata/source validation."""
        self._final_callback(lambda: self.clock.__setitem__(0, 1300.0))
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            self.run_preparation()

    def test_source_media_is_never_rehashed_or_observed_by_preparation(self) -> None:
        """Only original metadata documents may enter the byte reader after initial capture."""
        source_paths = {Path(row.path) for row in self.fixture.inputs.verified_media.snapshots}
        original = preparation.read_bytes

        def read(path: Path, maximum: int = 0) -> bytes:
            """Trip if a captured original source enters a metadata read path."""
            self.assertNotIn(path, source_paths)
            return original(path, maximum)

        with patch.object(preparation, "read_bytes", side_effect=read), \
                patch("color.grade_project_authority.file_hash", side_effect=AssertionError("no source rehash")), \
                patch("color.grade_project_authority.observe_project", side_effect=AssertionError("no observation")):
            self.assertEqual(len(self.run_preparation()), 2)

    def test_fault_helper_refuses_external_production_source_before_write(self) -> None:
        """No metadata/source dependency from the repository can become a fault target."""
        with patch.object(Path, "write_bytes") as write, self.assertRaisesRegex(RuntimeError, "exact TEST root"):
            self._append(Path(preparation.__file__).resolve(strict=True))
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
