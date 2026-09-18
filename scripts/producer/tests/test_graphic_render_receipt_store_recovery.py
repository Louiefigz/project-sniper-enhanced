"""Pending-set identity recovery tests for the graphic receipt store."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _graphic_render_receipt_store_fixture import graphic_receipt_store_fixture
from headless import graphic_render_receipt_store_io as store_io
from headless.graphic_render_receipt_semantics import (
    GraphicRenderReceiptV1,
    parse_graphic_render_receipt_v1,
)
from headless.graphic_render_receipt_store import (
    store_graphic_render_receipt_set,
)
from headless.graphic_render_receipt_store_types import (
    GraphicRenderReceiptStoreError,
    StoredGraphicRenderReceiptSetV1,
)


class GraphicRenderReceiptStoreRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.fixture = graphic_receipt_store_fixture(root)

    def _store(
        self, receipt: GraphicRenderReceiptV1
    ) -> StoredGraphicRenderReceiptSetV1:
        return store_graphic_render_receipt_set(
            self.fixture.attempt_root,
            self.fixture.expectation,
            (receipt,),
        )

    def test_conflicting_writer_cannot_erase_a_crashed_pending_identity(
        self,
    ) -> None:
        original_write = store_io._write_one
        writes = 0

        def crash(directory_fd: int, name: str, raw: bytes) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("crash after first retained file")
            original_write(directory_fd, name, raw)

        with mock.patch.object(store_io, "_write_one", side_effect=crash):
            with self.assertRaises(GraphicRenderReceiptStoreError):
                self._store(self.fixture.receipt)
        pending = (
            Path(self.fixture.attempt_root)
            / "work"
            / store_io.STORE_NAME
            / store_io.PENDING_NAME
        )
        retained = (pending / "receipt-0000.json").read_bytes()
        document = json.loads(self.fixture.receipt.document_json)
        document["media"]["artifact"]["sha256"] = "9" * 64
        document["renderArtifactDigest"] = "9" * 64
        conflicting = parse_graphic_render_receipt_v1(canonical(document))
        with self.assertRaisesRegex(
            GraphicRenderReceiptStoreError, "another set"
        ):
            self._store(conflicting)
        self.assertEqual(
            (pending / "receipt-0000.json").read_bytes(), retained
        )
        recovered = self._store(self.fixture.receipt)
        self.assertFalse(recovered.replayed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
