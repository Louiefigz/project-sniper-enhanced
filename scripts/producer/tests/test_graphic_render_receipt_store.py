"""Crash, replay, and hostile-byte tests for atomic graphic receipt sets."""

from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _graphic_render_receipt_store_fixture import (
    GraphicReceiptStoreFixtureV1,
    graphic_receipt_store_fixture,
)
from headless import graphic_render_receipt_store_io as store_io
from headless import graphic_render_receipt_store_reader as store_reader
from headless.graphic_render_receipt_store import (
    load_graphic_render_receipt_set,
    store_graphic_render_receipt_set,
    try_load_graphic_render_receipt_set,
)
from headless.graphic_render_receipt_store_types import (
    GraphicRenderReceiptStoreError,
    StoredGraphicRenderReceiptSetV1,
)


class GraphicRenderReceiptStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = graphic_receipt_store_fixture(self.root)

    def _store(
        self, fixture: GraphicReceiptStoreFixtureV1 | None = None
    ) -> StoredGraphicRenderReceiptSetV1:
        value = fixture or self.fixture
        return store_graphic_render_receipt_set(
            value.attempt_root, value.expectation, (value.receipt,)
        )

    def _final(self) -> Path:
        return (
            Path(self.fixture.attempt_root)
            / "work"
            / store_io.STORE_NAME
            / store_io.FINAL_NAME
        )

    def test_atomic_store_load_and_exact_replay_remain_nonauthorizing(
        self,
    ) -> None:
        created = self._store()
        replayed = self._store()
        loaded = load_graphic_render_receipt_set(
            self.fixture.attempt_root,
            self.fixture.expectation,
            created.locator,
        )
        probed = try_load_graphic_render_receipt_set(
            self.fixture.attempt_root, self.fixture.expectation
        )
        self.assertFalse(created.replayed)
        self.assertTrue(replayed.replayed)
        self.assertTrue(loaded.replayed)
        self.assertEqual(probed, loaded)
        self.assertEqual(created.receipts, (self.fixture.receipt,))
        self.assertFalse(created.receipts[0].claims.execution_authorized)
        self.assertFalse(created.receipts[0].claims.publication_authorized)

    def test_concurrent_identical_writers_create_once_then_exactly_replay(
        self,
    ) -> None:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(self._store) for _ in range(2))
            results = tuple(future.result() for future in futures)
        self.assertEqual(
            sorted(result.replayed for result in results), [False, True]
        )
        self.assertEqual(results[0].receipts, results[1].receipts)

    def test_pre_rename_crash_leaves_no_final_and_safe_retry_repairs(
        self,
    ) -> None:
        original = store_io._write_one
        calls = 0

        def crash(directory_fd: int, name: str, raw: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated power loss")
            original(directory_fd, name, raw)

        with mock.patch.object(store_io, "_write_one", side_effect=crash):
            with self.assertRaisesRegex(
                GraphicRenderReceiptStoreError, "cannot persist"
            ) as raised:
                self._store()
        self.assertIsInstance(raised.exception.__cause__, OSError)
        store = self._final().parent
        self.assertFalse(self._final().exists())
        self.assertTrue((store / store_io.PENDING_NAME).is_dir())
        repaired = self._store()
        self.assertFalse(repaired.replayed)
        self.assertTrue(self._final().is_dir())
        self.assertFalse((store / store_io.PENDING_NAME).exists())

    def test_crash_after_atomic_publish_replays_without_rewrite(self) -> None:
        created = self._store()
        before = (self._final() / "manifest.json").stat()
        recovered = try_load_graphic_render_receipt_set(
            self.fixture.attempt_root, self.fixture.expectation
        )
        after = (self._final() / "manifest.json").stat()
        self.assertIsNotNone(recovered)
        self.assertTrue(recovered.replayed)
        self.assertEqual(recovered.locator, created.locator)
        self.assertEqual(
            (before.st_ino, before.st_mtime_ns),
            (after.st_ino, after.st_mtime_ns),
        )

    def test_failed_publication_fsync_requires_full_final_replay_barrier(
        self,
    ) -> None:
        with mock.patch.object(
            store_io,
            "_sync_publication",
            side_effect=OSError("store fsync interrupted"),
        ):
            with self.assertRaisesRegex(
                GraphicRenderReceiptStoreError, "cannot persist"
            ):
                self._store()
        self.assertTrue(self._final().is_dir())
        with mock.patch.object(
            store_reader,
            "_sync_replay_directories",
            side_effect=OSError("replay fsync interrupted"),
        ):
            with self.assertRaisesRegex(
                GraphicRenderReceiptStoreError, "cannot persist"
            ):
                self._store()
        reader = store_reader._open_retained
        sync = store_reader._sync_replay_directories
        with mock.patch.object(
            store_reader, "_open_retained", wraps=reader
        ) as reads, mock.patch.object(
            store_reader, "_sync_replay_directories", wraps=sync
        ) as directories:
            recovered = self._store()
        replay_reads = [
            call.args[1] for call in reads.call_args_list if call.args[3]
        ]
        self.assertEqual(replay_reads, ["manifest.json", "receipt-0000.json"])
        directories.assert_called_once()
        self.assertTrue(recovered.replayed)

    def test_malformed_retained_manifest_and_receipt_bytes_fail_closed(
        self,
    ) -> None:
        for name in ("manifest.json", "receipt-0000.json"):
            with self.subTest(name=name):
                child = self.root / name.replace(".", "-")
                child.mkdir(mode=0o700)
                fixture = graphic_receipt_store_fixture(child)
                self._store(fixture)
                final = (
                    Path(fixture.attempt_root)
                    / "work"
                    / store_io.STORE_NAME
                    / store_io.FINAL_NAME
                )
                (final / name).write_bytes(b"{malformed")
                os.chmod(final / name, 0o600)
                with self.assertRaises(RuntimeError):
                    try_load_graphic_render_receipt_set(
                        fixture.attempt_root, fixture.expectation
                    )

    def test_unsafe_or_ambiguous_retained_state_fails_closed(self) -> None:
        self._store()
        receipt = self._final() / "receipt-0000.json"
        receipt.chmod(0o644)
        with self.assertRaises(RuntimeError):
            try_load_graphic_render_receipt_set(
                self.fixture.attempt_root, self.fixture.expectation
            )
        receipt.chmod(0o600)
        (self._final().parent / store_io.PENDING_NAME).mkdir(mode=0o700)
        with self.assertRaises(GraphicRenderReceiptStoreError):
            try_load_graphic_render_receipt_set(
                self.fixture.attempt_root, self.fixture.expectation
            )

    def test_missing_extra_symlink_and_hardlink_receipts_fail_closed(
        self,
    ) -> None:
        def mutate(case: str, final: Path) -> None:
            receipt = final / "receipt-0000.json"
            if case == "missing":
                receipt.unlink()
            elif case == "extra":
                extra = final / "extra.json"
                extra.write_bytes(b"{}")
                extra.chmod(0o600)
            elif case == "symlink":
                receipt.unlink()
                receipt.symlink_to(final / "manifest.json")
            else:
                os.link(
                    receipt, final.parent.parent / "external-hardlink.json"
                )

        for case in ("missing", "extra", "symlink", "hardlink"):
            with self.subTest(case=case):
                parent = self.root / f"unsafe-{case}"
                parent.mkdir(mode=0o700)
                fixture = graphic_receipt_store_fixture(parent)
                self._store(fixture)
                final = (
                    Path(fixture.attempt_root)
                    / "work"
                    / store_io.STORE_NAME
                    / store_io.FINAL_NAME
                )
                mutate(case, final)
                with self.assertRaises(RuntimeError):
                    try_load_graphic_render_receipt_set(
                        fixture.attempt_root, fixture.expectation
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
