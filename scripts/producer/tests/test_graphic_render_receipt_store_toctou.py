"""Inode-replacement regressions for retained graphic receipt replay."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _graphic_render_receipt_store_fixture import graphic_receipt_store_fixture
from headless import graphic_render_receipt_store_io as store_io
from headless import graphic_render_receipt_store_reader as store_reader
from headless.graphic_render_receipt_store import (
    store_graphic_render_receipt_set,
)
from headless.graphic_render_receipt_store_types import (
    GraphicRenderReceiptStoreError,
    StoredGraphicRenderReceiptSetV1,
)


class GraphicRenderReceiptStoreToctouTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.fixture = graphic_receipt_store_fixture(root)
        store_graphic_render_receipt_set(
            self.fixture.attempt_root,
            self.fixture.expectation,
            (self.fixture.receipt,),
        )
        self.final = (
            Path(self.fixture.attempt_root)
            / "work"
            / store_io.STORE_NAME
            / store_io.FINAL_NAME
        )

    def _replay(self) -> StoredGraphicRenderReceiptSetV1:
        return store_graphic_render_receipt_set(
            self.fixture.attempt_root,
            self.fixture.expectation,
            (self.fixture.receipt,),
        )

    def test_same_byte_file_replacement_during_fsync_fails_then_recovers(
        self,
    ) -> None:
        sync = store_reader._sync_replay_directories

        def replace_then_sync(final_fd: int, store_fd: int) -> None:
            receipt = self.final / "receipt-0000.json"
            replacement = self.final / ".same-bytes-replacement"
            replacement.write_bytes(receipt.read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, receipt)
            sync(final_fd, store_fd)

        with mock.patch.object(
            store_reader,
            "_sync_replay_directories",
            side_effect=replace_then_sync,
        ):
            with self.assertRaisesRegex(
                GraphicRenderReceiptStoreError, "replaced"
            ):
                self._replay()
        recovered = self._replay()
        self.assertTrue(recovered.replayed)
        self.assertEqual(recovered.receipts, (self.fixture.receipt,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
